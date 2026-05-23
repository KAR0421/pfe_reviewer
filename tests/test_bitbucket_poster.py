"""Tests for the Bitbucket PR comment poster."""
from __future__ import annotations

import base64
import io
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import pytest

from reviewer.integrations import bitbucket_poster
from reviewer.integrations.bitbucket_poster import (
    BitbucketPostError,
    main,
    post_comment,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report() -> dict:
    return {
        "metadata": {
            "tool": "REVIEWER",
            "version": "1.0.0",
            "timestamp": "2026-05-23T00:00:00Z",
            "directory": "/x",
        },
        "summary": {
            "total": 0,
            "by_severity": {"error": 0, "warning": 0, "info": 0},
            "by_category": {},
            "pack_count": 0,
            "bizrule_count": 0,
        },
        "packs": [],
    }


def _ok_response(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: False
    return resp


def _kwargs(**overrides):
    base = dict(
        bitbucket_url="https://bb.example.com",
        project="IM",
        repo="nximpress",
        pr_id=123,
        username="user",
        token="token",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# post_comment tests
# ---------------------------------------------------------------------------

def test_post_comment_builds_correct_url() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs())
    req = mock.call_args[0][0]
    assert req.full_url == (
        "https://bb.example.com/rest/api/1.0/projects/IM"
        "/repos/nximpress/pull-requests/123/comments"
    )


def test_post_comment_sends_correct_headers() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs())
    req = mock.call_args[0][0]
    # urllib lower-cases header keys.
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["content-type"] == "application/json"
    assert headers["accept"] == "application/json"
    assert headers["authorization"].startswith("Basic ")


def test_post_comment_sends_json_body() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs())
    req = mock.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert "text" in body
    assert isinstance(body["text"], str)
    assert body["text"].strip() != ""


def test_post_comment_passes_report_url_to_formatter() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(),
                     report_url="https://x/y", **_kwargs())
    req = mock.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert "https://x/y" in body["text"]


def test_post_comment_returns_parsed_response() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 42, "version": 0})):
        out = post_comment(_report(), **_kwargs())
    assert out == {"id": 42, "version": 0}


def test_post_comment_raises_on_http_error() -> None:
    err = HTTPError(
        url="https://bb/x", code=401, msg="Unauthorized", hdrs=None,
        fp=io.BytesIO(b'{"error":"unauthorized"}'),
    )
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      side_effect=err):
        with pytest.raises(BitbucketPostError) as exc_info:
            post_comment(_report(), **_kwargs())
    assert exc_info.value.status_code == 401
    assert "unauthorized" in exc_info.value.body


def test_post_comment_raises_on_connection_failure() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      side_effect=URLError("name resolution failed")):
        with pytest.raises(BitbucketPostError) as exc_info:
            post_comment(_report(), **_kwargs())
    assert exc_info.value.status_code == 0
    assert "name resolution failed" in exc_info.value.body


def test_post_comment_strips_trailing_slash_from_url() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(),
                     **_kwargs(bitbucket_url="https://bb.example.com/"))
    req = mock.call_args[0][0]
    assert "com//rest" not in req.full_url
    assert req.full_url.startswith("https://bb.example.com/rest/api/1.0/")


def test_post_comment_url_quotes_special_chars() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs(project="MY PROJ", repo="my repo"))
    req = mock.call_args[0][0]
    assert "MY%20PROJ" in req.full_url
    assert "my%20repo" in req.full_url
    assert " " not in req.full_url


def test_post_comment_authorization_header_is_basic_base64() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs(username="alice", token="s3cret"))
    req = mock.call_args[0][0]
    headers = {k.lower(): v for k, v in req.header_items()}
    auth = headers["authorization"]
    assert auth.startswith("Basic ")
    decoded = base64.b64decode(auth[len("Basic "):]).decode("utf-8")
    assert decoded == "alice:s3cret"


def test_post_comment_body_includes_markdown_markers() -> None:
    with patch.object(bitbucket_poster.urllib.request, "urlopen",
                      return_value=_ok_response({"id": 1})) as mock:
        post_comment(_report(), **_kwargs())
    req = mock.call_args[0][0]
    body = json.loads(req.data.decode("utf-8"))
    assert "## 🤖 REVIEWER" in body["text"]


def test_bitbucket_post_error_carries_status_and_body() -> None:
    err = BitbucketPostError(404, "not found")
    assert err.status_code == 404
    assert err.body == "not found"
    assert "404" in str(err)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def _write_report(tmp_path) -> str:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(_report()), encoding="utf-8")
    return str(p)


_CLI_BASE = [
    "--bitbucket-url", "https://bb.example.com",
    "--project", "IM", "--repo", "nximpress", "--pr", "123",
]


def test_cli_exits_2_when_username_missing(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("BB_USERNAME", raising=False)
    monkeypatch.setenv("BB_TOKEN", "tok")
    rc = main([_write_report(tmp_path), *_CLI_BASE])
    assert rc == 2
    assert "BB_USERNAME" in capsys.readouterr().err


def test_cli_exits_2_when_token_missing(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BB_USERNAME", "user")
    monkeypatch.delenv("BB_TOKEN", raising=False)
    rc = main([_write_report(tmp_path), *_CLI_BASE])
    assert rc == 2
    assert "BB_TOKEN" in capsys.readouterr().err


def test_cli_prints_comment_id_on_success(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BB_USERNAME", "user")
    monkeypatch.setenv("BB_TOKEN", "tok")
    with patch.object(bitbucket_poster, "post_comment",
                      return_value={"id": 999}):
        rc = main([_write_report(tmp_path), *_CLI_BASE])
    assert rc == 0
    assert "Comment posted: 999" in capsys.readouterr().out


def test_cli_exits_1_on_post_error(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("BB_USERNAME", "user")
    monkeypatch.setenv("BB_TOKEN", "tok")
    with patch.object(bitbucket_poster, "post_comment",
                      side_effect=BitbucketPostError(500, "boom")):
        rc = main([_write_report(tmp_path), *_CLI_BASE])
    assert rc == 1
    assert "boom" in capsys.readouterr().err or "500" in capsys.readouterr().err
