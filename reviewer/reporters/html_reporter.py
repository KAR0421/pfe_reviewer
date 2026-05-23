"""Self-contained HTML report generator.

Given the JSON dict produced by
:func:`reviewer.reporters.json_reporter.to_json_dict`, render a single
self-contained HTML document (no external CSS / JS / fonts / icons)
suitable for use as a Jenkins build artifact.

The HTML structure is intentionally informal — it has no external
schema contract and may evolve. The contractual reporter is JSON; this
module is for humans.

Layout:

* ``<head>`` with embedded ``<style>``.
* A summary banner showing tool/version/timestamp, totals, severity
  breakdown, pack/BizRule counts, and the analysed directory.
* An optional table of contents (rendered only when more than one
  pack is present).
* One ``<section>`` per pack, each containing one subsection per
  BizRule that has at least one finding, with a findings table.
* A footer with the tool version and timestamp.

All user-supplied content (pack filenames, BizRule names, messages,
rule IDs, categories, directory paths) is escaped via
:func:`html.escape` to prevent script injection.
"""
from __future__ import annotations

import base64
import html
from importlib.resources import files
from pathlib import Path
from typing import Iterable


__all__ = ["to_html_string", "write_html"]


def _load_asset_b64(name: str) -> str:
    data = (files("reviewer.reporters.assets") / name).read_bytes()
    return base64.b64encode(data).decode("ascii")


_NEOXAM_ICON_B64 = _load_asset_b64("neoxam_icon.png")
_NEOXAM_WORDMARK_B64 = _load_asset_b64("neoxam_wordmark.png")
_NEOXAM_ICON_URI = f"data:image/png;base64,{_NEOXAM_ICON_B64}"
_NEOXAM_WORDMARK_URI = f"data:image/png;base64,{_NEOXAM_WORDMARK_B64}"


_SEVERITY_EMOJI = {"error": "🔴", "warning": "🟡", "info": "🔵"}
_UNKNOWN_EMOJI = "⚪"
_SEVERITY_LABELS = ("error", "warning", "info")


_STYLE = """
:root {
  color-scheme: dark;
  --bg-deep: #0a1426;
  --bg-panel: #131c2e;
  --bg-elev: #1a2540;
  --accent: #1ec8b4;
  --accent-dim: #14a594;
  --text-strong: #ffffff;
  --text-body: #e2e8f0;
  --text-muted: #8b9bb5;
  --border: #243049;
  --sev-error-bg: #2d1620;
  --sev-error-text: #ff7a8a;
  --sev-warning-bg: #2d2516;
  --sev-warning-text: #f5c060;
  --sev-info-bg: #16242d;
  --sev-info-text: #5cb8d6;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-weight: 400;
  color: var(--text-body);
  background: var(--bg-deep);
  line-height: 1.5;
}
h1, h2, h3 { font-weight: 600; color: var(--text-strong); }
main {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem;
}
.brand {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.brand-icon {
  height: 56px;
  width: auto;
  flex-shrink: 0;
}
.brand-text {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.brand-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.8rem;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: 0.02em;
  margin: 0;
  line-height: 1;
}
.brand-title svg {
  width: 22px;
  height: 22px;
  color: var(--accent);
  flex-shrink: 0;
}
.brand-tagline {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted);
  font-weight: 400;
}
header.banner {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-bottom: 2px solid var(--accent);
  border-radius: 8px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}
header.banner h1 {
  margin: 0 0 0.4rem;
  font-size: 1.4rem;
  color: var(--accent);
}
header.banner .meta {
  font-size: 0.9rem;
  color: var(--text-muted);
}
.summary-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem 2rem;
  margin-top: 0.8rem;
  font-size: 0.95rem;
}
.summary-grid .item { color: var(--text-body); }
.summary-grid .item strong { color: var(--text-strong); }
.summary-grid code {
  background: var(--bg-elev);
  padding: 0.05rem 0.4rem;
  border-radius: 3px;
  color: var(--text-body);
  font-size: 0.85rem;
}
.severity-counts {
  display: inline-flex;
  gap: 0.8rem;
  flex-wrap: wrap;
}
nav.toc {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.9rem 1.1rem;
  margin-bottom: 1.5rem;
}
nav.toc h2 {
  font-size: 1rem;
  margin: 0 0 0.4rem;
  color: var(--text-strong);
}
nav.toc ul { margin: 0; padding-left: 1.2rem; }
nav.toc a { color: var(--accent); text-decoration: none; }
nav.toc a:hover { color: var(--accent-dim); text-decoration: underline; }
section.pack {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.25rem;
  margin-bottom: 1.5rem;
}
section.pack > h2 {
  font-size: 1.25rem;
  color: var(--accent);
  margin: 0 0 0.8rem;
}
section.bizrule { margin: 0.8rem 0 1.2rem; }
section.bizrule > h3 {
  font-size: 1.05rem;
  margin: 0 0 0.5rem;
  color: var(--text-strong);
}
.badge {
  display: inline-block;
  font-size: 0.78rem;
  padding: 0.05rem 0.55rem;
  margin-left: 0.5rem;
  border-radius: 10px;
  background: var(--bg-elev);
  color: var(--text-muted);
  vertical-align: middle;
  font-weight: 400;
}
table.findings {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
  background: transparent;
}
table.findings th, table.findings td {
  text-align: left;
  padding: 0.45rem 0.65rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  color: var(--text-body);
}
table.findings thead th {
  background: var(--bg-elev);
  color: var(--text-muted);
  font-weight: 600;
  border-bottom: 1px solid var(--border);
  text-transform: uppercase;
  font-size: 0.78rem;
  letter-spacing: 0.04em;
}
table.findings tbody tr:nth-child(odd) { background: var(--bg-panel); }
table.findings tbody tr:nth-child(even) { background: var(--bg-elev); }
table.findings tr.severity-error    { background: var(--sev-error-bg) !important; }
table.findings tr.severity-warning  { background: var(--sev-warning-bg) !important; }
table.findings tr.severity-info     { background: var(--sev-info-bg) !important; }
table.findings tr.severity-error td.col-severity   { color: var(--sev-error-text); font-weight: 600; }
table.findings tr.severity-warning td.col-severity { color: var(--sev-warning-text); font-weight: 600; }
table.findings tr.severity-info td.col-severity    { color: var(--sev-info-text); font-weight: 600; }
table.findings td.col-line { font-variant-numeric: tabular-nums; width: 4rem; color: var(--text-muted); }
table.findings td.col-rule { font-family: ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace; width: 5rem; color: var(--accent); }
table.findings td.col-category { width: 7rem; color: var(--text-muted); }
table.findings td.col-severity { width: 6rem; }
table.findings td.col-message { word-break: break-word; }
.empty-block {
  padding: 1.25rem;
  background: #0d3526;
  border: 1px solid #1c6b4a;
  border-radius: 8px;
  color: #6dd8a4;
  font-size: 1rem;
}
.pack-empty {
  margin: 0;
  color: #6dd8a4;
  font-size: 0.95rem;
}
footer.report-footer {
  margin-top: 2.5rem;
  padding-top: 0.8rem;
  border-top: 1px solid var(--border);
  font-size: 0.85rem;
  color: var(--text-muted);
}
footer.report-footer > p { margin: 0 0 0.35rem; }
.powered-by {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin: 0.4rem 0 0;
  font-size: 0.85rem;
  color: var(--text-muted);
}
.powered-wordmark {
  height: 20px;
  width: auto;
  vertical-align: middle;
}
@media (max-width: 800px) {
  main { padding: 1rem 0.75rem 2rem; }
  table.findings { font-size: 0.85rem; }
  .brand-title { font-size: 1.5rem; }
}
@media print {
  body { background: #ffffff; color: #1f2933; }
  h1, h2, h3 { color: #0f172a; }
  header.banner, nav.toc, section.pack {
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    color: #1f2933;
  }
  header.banner h1, section.pack > h2, nav.toc a { color: var(--accent); }
  nav.toc, .powered-by { display: none; }
  .brand-icon { filter: brightness(0); }
  table.findings thead th { background: #f1f5f9 !important; color: #334155 !important; }
  table.findings th, table.findings td { color: #1f2933 !important; border-bottom: 1px solid #cbd5e1; }
  table.findings tbody tr:nth-child(odd),
  table.findings tbody tr:nth-child(even) { background: #ffffff !important; }
  table.findings tr.severity-error    { background: #fdecec !important; }
  table.findings tr.severity-warning  { background: #fdf6dc !important; }
  table.findings tr.severity-info     { background: #eaf3fa !important; }
  table.findings td.col-rule { color: var(--accent-dim) !important; }
  .badge { background: #e2e8f0 !important; color: #334155 !important; }
  .empty-block { background: #ecfdf5 !important; color: #065f46 !important; border-color: #a7f3d0 !important; }
}
""".strip()


_LENS_SVG = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'aria-hidden="true">'
    '<circle cx="11" cy="11" r="7"/>'
    '<path d="m21 21-4.35-4.35"/>'
    '</svg>'
)


def _render_brand() -> str:
    return (
        '<div class="brand">\n'
        f'  <img src="{_NEOXAM_ICON_URI}" alt="NeoXam" class="brand-icon" />\n'
        '  <div class="brand-text">\n'
        f'    <h1 class="brand-title">{_LENS_SVG} REVIEWER</h1>\n'
        '    <p class="brand-tagline">Static Analysis for BizRule</p>\n'
        '  </div>\n'
        '</div>'
    )


def _e(value: object) -> str:
    """HTML-escape ``value`` after coercing it to ``str``."""
    return html.escape(str(value), quote=True)


def _severity_emoji(severity: str) -> str:
    return _SEVERITY_EMOJI.get(severity, _UNKNOWN_EMOJI)


def _slugify_pack(pack_file: str, index: int) -> str:
    safe = "".join(
        ch.lower() if ch.isalnum() else "-" for ch in pack_file
    ).strip("-")
    return f"pack-{index}-{safe}" if safe else f"pack-{index}"


def _render_banner(metadata: dict, summary: dict) -> str:
    by_sev = summary.get("by_severity", {})
    errors = int(by_sev.get("error", 0))
    warnings = int(by_sev.get("warning", 0))
    infos = int(by_sev.get("info", 0))
    parts = [
        '<header class="banner">',
        f'  <h1>REVIEWER Report</h1>',
        '  <div class="meta">',
        f'    <span>{_e(metadata.get("tool", "REVIEWER"))} '
        f'v{_e(metadata.get("version", ""))}</span>'
        f' &middot; <span>{_e(metadata.get("timestamp", ""))}</span>',
        '  </div>',
        '  <div class="summary-grid">',
        f'    <div class="item"><strong>Total findings:</strong> '
        f'{int(summary.get("total", 0))}</div>',
        '    <div class="item severity-counts">'
        f'<span>🔴 {errors} errors</span>'
        f'<span>🟡 {warnings} warnings</span>'
        f'<span>🔵 {infos} info</span>'
        '</div>',
        f'    <div class="item"><strong>Packs:</strong> '
        f'{int(summary.get("pack_count", 0))}</div>',
        f'    <div class="item"><strong>BizRules:</strong> '
        f'{int(summary.get("bizrule_count", 0))}</div>',
        f'    <div class="item"><strong>Directory:</strong> '
        f'<code>{_e(metadata.get("directory", ""))}</code></div>',
        '  </div>',
        '</header>',
    ]
    return "\n".join(parts)


def _render_toc(packs: list[dict]) -> str:
    items = []
    for i, pack in enumerate(packs):
        pack_file = pack.get("pack_file", "")
        anchor = _slugify_pack(pack_file, i)
        items.append(
            f'    <li><a href="#{_e(anchor)}">{_e(pack_file)}</a></li>'
        )
    return (
        '<nav class="toc">\n'
        '  <h2>Packs</h2>\n'
        '  <ul>\n'
        + "\n".join(items) + "\n"
        '  </ul>\n'
        '</nav>'
    )


def _render_finding_row(finding: dict) -> str:
    severity = str(finding.get("severity", ""))
    sev_class = f"severity-{severity}" if severity in _SEVERITY_LABELS else "severity-unknown"
    emoji = _severity_emoji(severity)
    return (
        f'        <tr class="{sev_class}">\n'
        f'          <td class="col-line">{int(finding.get("line", 0) or 0)}</td>\n'
        f'          <td class="col-rule">{_e(finding.get("rule_id", ""))}</td>\n'
        f'          <td class="col-category">{_e(finding.get("category", ""))}</td>\n'
        f'          <td class="col-severity">{emoji} {_e(severity)}</td>\n'
        f'          <td class="col-message">{_e(finding.get("message", ""))}</td>\n'
        f'        </tr>'
    )


def _render_bizrule(bizrule: dict) -> str:
    findings = bizrule.get("findings", []) or []
    name = bizrule.get("name", "")
    count = len(findings)
    rows = "\n".join(_render_finding_row(f) for f in findings)
    return (
        '  <section class="bizrule">\n'
        f'    <h3>{_e(name)}<span class="badge">{count} finding'
        f'{"" if count == 1 else "s"}</span></h3>\n'
        '    <table class="findings">\n'
        '      <thead>\n'
        '        <tr>\n'
        '          <th>Line</th><th>Rule</th><th>Category</th>'
        '<th>Severity</th><th>Message</th>\n'
        '        </tr>\n'
        '      </thead>\n'
        '      <tbody>\n'
        f'{rows}\n'
        '      </tbody>\n'
        '    </table>\n'
        '  </section>'
    )


def _render_pack(pack: dict, index: int) -> str:
    pack_file = pack.get("pack_file", "")
    anchor = _slugify_pack(pack_file, index)
    bizrules = pack.get("bizrules", []) or []
    bizrules_with_findings = [
        br for br in bizrules if (br.get("findings") or [])
    ]
    body_parts: list[str] = []
    if not bizrules_with_findings:
        body_parts.append(
            '  <p class="pack-empty">✅ No issues found in this pack.</p>'
        )
    else:
        for br in bizrules_with_findings:
            body_parts.append(_render_bizrule(br))
    return (
        f'<section class="pack" id="{_e(anchor)}">\n'
        f'  <h2>{_e(pack_file)}</h2>\n'
        + "\n".join(body_parts) + "\n"
        '</section>'
    )


def _render_footer(metadata: dict) -> str:
    return (
        '<footer class="report-footer">\n'
        f'  <p>Generated by REVIEWER v{_e(metadata.get("version", ""))} '
        f'at {_e(metadata.get("timestamp", ""))}</p>\n'
        '  <p class="powered-by">\n'
        '    Powered by\n'
        f'    <img src="{_NEOXAM_WORDMARK_URI}" alt="NeoXam" class="powered-wordmark" />\n'
        '    REVIEWER\n'
        '  </p>\n'
        '</footer>'
    )


def to_html_string(report_data: dict) -> str:
    """Render ``report_data`` as a self-contained HTML document.

    Pure function — no I/O. All user-supplied strings are HTML-escaped.
    """
    metadata = report_data.get("metadata", {}) or {}
    summary = report_data.get("summary", {}) or {}
    packs = report_data.get("packs", []) or []
    total = int(summary.get("total", 0))

    banner = _render_banner(metadata, summary)
    footer = _render_footer(metadata)

    body_chunks: list[str] = [_render_brand(), banner]

    if total == 0:
        body_chunks.append(
            '<div class="empty-block">'
            '<strong>✅ No issues found.</strong>'
            '</div>'
        )
    else:
        if len(packs) > 1:
            body_chunks.append(_render_toc(packs))
        for i, pack in enumerate(packs):
            body_chunks.append(_render_pack(pack, i))

    body_chunks.append(footer)
    body_html = "\n".join(body_chunks)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>REVIEWER Report</title>\n"
        "  <style>\n"
        f"{_STYLE}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        f"{body_html}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def write_html(report_data: dict, output_path: str | Path) -> None:
    """Write the rendered HTML to ``output_path`` as UTF-8.

    Parent directories are created if they do not exist.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_html_string(report_data), encoding="utf-8")
