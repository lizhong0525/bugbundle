"""Static HTML viewer for a bundle.

Renders a single self-contained HTML report (screenshots embedded as
base64) so a reviewer can inspect every artifact without any tooling.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

from .bundle import Bundle, BundleError, load_bundle

_LEVEL_CLASS = {"error": "err", "warning": "warn", "warn": "warn", "pageerror": "err"}


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _embed_screenshot(bundle: Bundle, name: str) -> str:
    path = bundle.root / "screenshots" / name
    if not path.is_file():
        return ""
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def render_html(bundle: Bundle) -> str:
    """Render the loaded bundle to a standalone HTML string."""
    m = bundle.manifest
    failed_requests = [r for r in bundle.network if r.get("failed") or (r.get("status") or 0) >= 400]

    step_rows = []
    for i, step in enumerate(bundle.steps, 1):
        shot = step.get("screenshot")
        img = ""
        if shot:
            src = _embed_screenshot(bundle, shot)
            img = (
                f'<a href="{src}" target="_blank"><img class="shot" src="{src}" '
                f'alt="screenshot step {i}"></a>'
                if src
                else f'<span class="missing">missing: {_esc(shot)}</span>'
            )
        step_rows.append(
            "<tr>"
            f"<td>{i}</td><td>{_esc(step.get('t'))}</td>"
            f"<td>{_esc(step.get('action'))}</td>"
            f"<td><code>{_esc(step.get('target'))}</code></td>"
            f"<td>{_esc(step.get('note', ''))}</td><td>{img}</td>"
            "</tr>"
        )

    console_rows = "".join(
        f'<tr class="{_LEVEL_CLASS.get(str(e.get("level", "")).lower(), "")}">'
        f"<td>{_esc(e.get('t'))}</td><td>{_esc(e.get('level'))}</td>"
        f"<td><pre>{_esc(e.get('text'))}</pre></td></tr>"
        for e in bundle.console
    )

    def net_row(r: dict) -> str:
        status = r.get("status")
        bad = r.get("failed") or (status or 0) >= 400
        cls = ' class="err"' if bad else ""
        detail = r.get("error") or ("" if status is None else "")
        return (
            f"<tr{cls}><td>{_esc(r.get('t'))}</td><td>{_esc(r.get('method'))}</td>"
            f"<td><code>{_esc(r.get('url'))}</code></td>"
            f"<td>{_esc('FAILED' if r.get('failed') else status)}</td>"
            f"<td>{_esc(detail)}</td></tr>"
        )

    network_rows = "".join(net_row(r) for r in bundle.network)
    dom = bundle.dom_snapshot
    dom_block = (
        f"<details><summary>DOM snapshot (redacted, {len(dom)} chars)</summary>"
        f"<pre>{_esc(dom)}</pre></details>"
        if dom is not None
        else "<p><em>No DOM snapshot in this bundle.</em></p>"
    )

    flags = []
    if not m.get("passwords_recorded", False):
        flags.append("passwords not recorded")
    if not m.get("hidden_inputs_recorded", False):
        flags.append("hidden inputs not recorded")
    privacy = ", ".join(flags) if flags else "review flags manually"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>BugBundle report - {_esc(m.get('url', 'unknown page'))}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: .9rem; }}
th, td {{ border: 1px solid #ccc; padding: .35rem .5rem; text-align: left; vertical-align: top; }}
th {{ background: #f0f0f0; }}
tr.err td {{ background: #ffe5e5; }} tr.warn td {{ background: #fff7d6; }}
pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
code {{ word-break: break-all; }}
img.shot {{ max-width: 220px; border: 1px solid #999; }}
.banner {{ background: #ffd23e; padding: .6rem .9rem; border-radius: 6px; font-weight: 600; }}
.meta {{ color: #555; font-size: .85rem; }}
.missing {{ color: #a00; }}
details pre {{ background: #f7f7f7; padding: .8rem; max-height: 320px; overflow: auto; }}
</style></head><body>
<p class="banner">BugBundle report &mdash; contains recorded browsing data. Review before sharing.</p>
<h1>Bug report: {_esc(m.get('url', '(unknown page)'))}</h1>
<p class="meta">
Format {_esc(m.get('format'))} &middot; captured {_esc(m.get('created_at'))} &middot;
viewport {_esc(json.dumps(m.get('viewport', {})))} &middot; {_esc(m.get('user_agent', ''))}<br>
Privacy: {_esc(privacy)}.
</p>

<h2>Steps ({len(bundle.steps)})</h2>
<table><tr><th>#</th><th>time</th><th>action</th><th>target</th><th>note</th><th>screenshot</th></tr>
{''.join(step_rows) or '<tr><td colspan="6"><em>No steps recorded.</em></td></tr>'}
</table>

<h2>Console &amp; page errors ({len(bundle.console)})</h2>
<table><tr><th>time</th><th>level</th><th>message</th></tr>
{console_rows or '<tr><td colspan="3"><em>Console is clean.</em></td></tr>'}
</table>

<h2>Network ({len(bundle.network)} requests, {len(failed_requests)} failed)</h2>
<table><tr><th>time</th><th>method</th><th>URL</th><th>status</th><th>error</th></tr>
{network_rows or '<tr><td colspan="5"><em>No network activity recorded.</em></td></tr>'}
</table>

<h2>DOM snapshot</h2>
{dom_block}
</body></html>"""


def render_to_file(bundle_root: Path, out_html: Path) -> Path:
    """Load a bundle directory and write a standalone HTML report."""
    bundle = load_bundle(bundle_root)
    out_html = Path(out_html)
    if bundle.dom_snapshot is None and not bundle.steps:
        raise BundleError("Bundle is empty (no steps and no DOM snapshot); nothing to render")
    out_html.write_text(render_html(bundle), encoding="utf-8")
    return out_html
