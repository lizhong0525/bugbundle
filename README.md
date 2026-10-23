# BugBundle

Portable, redacted browser bug-report bundles for local development and QA — capture what a broken page did (steps, console errors, failed requests, screenshots, DOM snapshot), redact the sensitive parts, inspect everything, then share a single zip only after explicit confirmation.

## Quickstart

```bash
python -m bugbundle demo
```

That's it — no browser, no Playwright, no dependencies. It loads the included sample bundle (`fixtures/sample_bundle/`), validates it, and writes a standalone HTML report you can open to inspect every artifact.

## Demo walkthrough

1. `python -m bugbundle demo --out report.html`
   Output shows the sample bundle's URL, viewport, and counts (4 steps, 4 console entries, 3 network requests / 2 failed), then the path to `report.html`.
2. Open `report.html`. You will see the captured steps with embedded screenshots, the console/page errors (including the intentional `TypeError`), the failed network calls (a 404 and an unresolvable host), and the redacted DOM snapshot. Note the yellow banner: *review before sharing*.
3. Try the round trip:
   ```bash
   python -m bugbundle export fixtures/sample_bundle --out share.zip   # asks you to type 'share'
   python -m bugbundle import share.bugbundle.zip --out /tmp/imported  # unpacks + validates
   python -m bugbundle view /tmp/imported                              # renders the same report
   ```
4. Optional live capture (requires `pip install playwright && playwright install chromium`):
   ```bash
   python -m bugbundle capture "file://$PWD/demo/index.html" --out captures/run1
   ```
   `demo/index.html` has four intentional bugs (uncaught TypeError, console.error with a leaky email, a 404 + unreachable fetch, a crashing form submit). While recording, a red banner is pinned to the top of the page so the capture is always visible.

## Features

- **Capture harness** (`bugbundle/capture.py`, Playwright optional): records clicks/inputs/submits, console messages, page errors, network responses and failures, viewport, URL, timestamps, and a DOM snapshot. A visible on-page indicator announces recording.
- **Redaction** (`bugbundle/redaction.py`): configurable rules for URL query parameters, form-field values, bearer/JWT tokens, email addresses, and DOM regions (`#id`, `.class`, tag). Password and hidden input values are **never** recorded or kept in snapshots.
- **Bundle format** (`bugbundle/bundle.py`): plain folder with `manifest.json`, `steps.json`, `console.json`, `network.json`, `dom_snapshot.html`, `screenshots/`. Validated on load; malformed JSON, missing files, wrong format version, and zip path-traversal are rejected with clear errors.
- **Viewer** (`bugbundle/viewer.py`): renders one self-contained HTML report (screenshots embedded as base64) so reviewers can inspect every artifact. HTML-escaped against injection from captured content.
- **Consent gate**: `export` lists exactly what will be shared and requires typing `share` (or `--yes` in scripts) before producing the zip.
- **Works without Playwright**: the entire test suite and the `demo`/`view`/`export`/`import`/`validate` commands run against saved fixtures — no browser download, no network, no keys.

## Tests

```bash
python -m pytest -q        # or: python -m unittest discover -s tests -v
```

Covers redaction rules, export/import round trip (including byte-identical screenshots), malformed/empty/hostile bundles, viewer rendering and HTML escaping, and the CLI.

## Known limitations

- DOM region redaction uses regex-based matching (stdlib only), not a real HTML parser; selectors are limited to `#id`, `.class`, and tag names, and pathological nested same-tag markup can over-match.
- Live capture records until page close/timeout; there is no scripted step replay yet.
- Screenshots are taken at the OS/browser level during live capture; per-step screenshot timing depends on the page.
- Redaction is best-effort pattern matching — the viewer + mandatory confirmation exist precisely so a human reviews artifacts before sharing.

## Roadmap

1. Per-step automatic screenshots and video/trace recording in the capture harness.
2. A redaction config file (`bugbundle.toml`) loadable per project.
3. Diff view between two bundles (regression reports).

## License

MIT — see [LICENSE](LICENSE).
