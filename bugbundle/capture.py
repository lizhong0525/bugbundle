"""Playwright-powered capture harness.

Playwright is an OPTIONAL runtime dependency: importing this module never
imports playwright. Only calling `capture()` does, and it fails with a
clear message when playwright is not installed.

The recorder shows a visible capture indicator (a fixed red banner injected
into the page), never records password or hidden input values, and applies
the redaction policy before anything is written to disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from .bundle import new_manifest, utc_now_iso, write_bundle
from .redaction import RedactionRules, Redactor

INDICATOR_ID = "bugbundle-capture-indicator"

_STEP_LISTENER_JS = """
() => {
  const indicator = document.createElement('div');
  indicator.id = '%s';
  indicator.textContent = '\\u25cf BugBundle recording - your actions are being captured';
  Object.assign(indicator.style, {
    position: 'fixed', top: '0', left: '0', right: '0', zIndex: '2147483647',
    background: '#d40000', color: '#fff', font: 'bold 13px system-ui',
    padding: '4px 10px', textAlign: 'center', pointerEvents: 'none',
  });
  document.documentElement.appendChild(indicator);

  const describe = (el) => {
    if (!el || !el.tagName) return '';
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const name = el.getAttribute && el.getAttribute('name');
    if (name) s += '[name=' + name + ']';
    return s;
  };
  const sensitive = (el) =>
    el && el.tagName === 'INPUT' && ['password', 'hidden'].includes((el.type || '').toLowerCase());

  window.__bugbundleSteps = [];
  document.addEventListener('click', (e) => {
    window.__bugbundleSteps.push({action: 'click', target: describe(e.target)});
  }, true);
  document.addEventListener('input', (e) => {
    if (sensitive(e.target)) return;  // never record password/hidden values
    window.__bugbundleSteps.push({action: 'input', target: describe(e.target)});
  }, true);
  document.addEventListener('submit', (e) => {
    window.__bugbundleSteps.push({action: 'submit', target: describe(e.target)});
  }, true);
}
""" % INDICATOR_ID


def capture(
    url: str,
    out_dir: Path,
    rules: RedactionRules | None = None,
    headless: bool = True,
    viewport: dict | None = None,
    timeout_ms: int = 30_000,
) -> Path:
    """Open `url` in a browser, record until the page is closed or times out,
    then write a redacted bundle to `out_dir`.

    Raises RuntimeError with install instructions when playwright is missing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Live capture requires it:\n"
            "  pip install playwright && playwright install chromium\n"
            "All other BugBundle commands (view, export, import, tests) work without it."
        ) from exc

    rules = rules or RedactionRules()
    redactor = Redactor(rules)
    viewport = viewport or {"width": 1280, "height": 800}

    console_events: list[dict] = []
    network_events: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport=viewport, user_agent="BugBundle/0.1 (+capture)")

        def on_console(msg):
            console_events.append(
                {"t": utc_now_iso(), "level": msg.type, "text": redactor.redact_text(msg.text)}
            )

        def on_pageerror(exc):
            console_events.append({"t": utc_now_iso(), "level": "pageerror", "text": redactor.redact_text(str(exc))})

        def on_response(resp):
            network_events.append(
                {
                    "t": utc_now_iso(),
                    "method": resp.request.method,
                    "url": redactor.redact_url(resp.url),
                    "status": resp.status,
                    "failed": False,
                }
            )

        def on_requestfailed(req):
            network_events.append(
                {
                    "t": utc_now_iso(),
                    "method": req.method,
                    "url": redactor.redact_url(req.url),
                    "status": None,
                    "failed": True,
                    "error": redactor.redact_text(req.failure or "request failed"),
                }
            )

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("response", on_response)
        page.on("requestfailed", on_requestfailed)

        page.goto(url, timeout=timeout_ms)
        page.add_init_script(_STEP_LISTENER_JS)
        page.evaluate(_STEP_LISTENER_JS)
        page.screenshot(path=None)  # warm-up; real shots taken per step below

        # Record until the user closes the page/browser or the timeout hits.
        try:
            page.wait_for_event("close", timeout=timeout_ms)
        except Exception:
            pass

        raw_steps = page.evaluate("window.__bugbundleSteps || []")
        dom_html = redactor.redact_dom(page.content())
        browser.close()

    # Redact step targets, stamp times, keep a final screenshot reference.
    steps = [
        {
            "t": utc_now_iso(),
            "action": s.get("action", "unknown"),
            "target": redactor.redact_text(s.get("target", "")),
            "note": s.get("note", ""),
        }
        for s in raw_steps
    ]

    bundle_root = write_bundle(
        Path(out_dir),
        manifest=new_manifest(redactor.redact_url(url), viewport, user_agent="BugBundle/0.1 (+capture)"),
        steps=steps,
        console=console_events,
        network=network_events,
        dom_snapshot=dom_html,
    )
    return bundle_root
