"""Post the formatted reviewer Markdown comment to a Bitbucket Server PR.

This module is the ONLY place in the reviewer that makes outbound
network calls. It targets Bitbucket Server (on-prem) REST API v1.0,
not Bitbucket Cloud. Only standard-library ``urllib`` is used — the
reviewer remains dependency-free.

Endpoint:
    POST {bitbucket_url}/rest/api/1.0/projects/{project}/repos/{repo}
         /pull-requests/{pr_id}/comments

Body:
    {"text": "<markdown body>"}

Auth: HTTP Basic with username + Personal Access Token (PAT).

CLI usage:
    python -m reviewer.integrations.bitbucket_poster report.json \\
        --bitbucket-url https://bb.example.com \\
        --project IM --repo nximpress --pr 123 \\
        [--report-url https://ci/reports/123.html]

Credentials are read from the BB_USERNAME and BB_TOKEN environment
variables. Both must be set and non-empty.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Sequence

from reviewer.reporters.comment_formatter import format_comment


__all__ = ["BitbucketPostError", "post_comment", "main"]


class BitbucketPostError(RuntimeError):
    """Raised when the Bitbucket comment POST fails."""

    def __init__(self, status_code: int, body: str, message: str = "") -> None:
        super().__init__(message or f"HTTP {status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


def _build_url(
    bitbucket_url: str, project: str, repo: str, pr_id: int | str
) -> str:
    base = bitbucket_url.rstrip("/")
    return (
        f"{base}/rest/api/1.0/projects/{urllib.parse.quote(str(project), safe='')}"
        f"/repos/{urllib.parse.quote(str(repo), safe='')}"
        f"/pull-requests/{urllib.parse.quote(str(pr_id), safe='')}/comments"
    )


def _build_auth_header(username: str, token: str) -> str:
    raw = f"{username}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def post_comment(
    report_data: dict,
    *,
    bitbucket_url: str,
    project: str,
    repo: str,
    pr_id: int | str,
    username: str,
    token: str,
    report_url: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Post the Markdown comment for ``report_data`` to the given PR.

    Returns the parsed JSON response from Bitbucket on success.
    Raises :class:`BitbucketPostError` on HTTP failure, connection
    failure, or missing required arguments.
    """
    if not bitbucket_url:
        raise BitbucketPostError(0, "", message="bitbucket_url is required")
    if not project:
        raise BitbucketPostError(0, "", message="project is required")
    if not repo:
        raise BitbucketPostError(0, "", message="repo is required")
    if pr_id is None or str(pr_id) == "":
        raise BitbucketPostError(0, "", message="pr_id is required")
    if not username:
        raise BitbucketPostError(0, "", message="username is required")
    if not token:
        raise BitbucketPostError(0, "", message="token is required")

    text = format_comment(report_data, report_url=report_url)
    url = _build_url(bitbucket_url, project, repo, pr_id)
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": _build_auth_header(username, token),
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        raise BitbucketPostError(status_code=err.code, body=err_body) from err
    except urllib.error.URLError as err:
        reason = str(getattr(err, "reason", err))
        raise BitbucketPostError(
            status_code=0,
            body=reason,
            message=f"Connection failure: {reason}",
        ) from err

    try:
        return json.loads(resp_body) if resp_body else {}
    except json.JSONDecodeError:
        return {"raw": resp_body}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reviewer.integrations.bitbucket_poster",
        description="Post the reviewer Markdown comment to a Bitbucket PR.",
    )
    parser.add_argument("report_json", help="Path to the JSON report file.")
    parser.add_argument("--bitbucket-url", required=True,
                        help="Base URL of Bitbucket Server.")
    parser.add_argument("--project", required=True, help="Project key.")
    parser.add_argument("--repo", required=True, help="Repository slug.")
    parser.add_argument("--pr", required=True, help="Pull request ID.")
    parser.add_argument("--report-url", default=None,
                        help="Public URL of the full HTML report.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    username = os.environ.get("BB_USERNAME", "")
    token = os.environ.get("BB_TOKEN", "")
    if not username:
        print("error: BB_USERNAME env var is missing or empty", file=sys.stderr)
        return 2
    if not token:
        print("error: BB_TOKEN env var is missing or empty", file=sys.stderr)
        return 2

    with open(args.report_json, "r", encoding="utf-8") as fh:
        report_data = json.load(fh)

    try:
        response = post_comment(
            report_data,
            bitbucket_url=args.bitbucket_url,
            project=args.project,
            repo=args.repo,
            pr_id=args.pr,
            username=username,
            token=token,
            report_url=args.report_url,
        )
    except BitbucketPostError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    comment_id = response.get("id", "?")
    print(f"Comment posted: {comment_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
