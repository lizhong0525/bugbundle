"""Command line interface for BugBundle.

Commands:
  demo      Build a report from the bundled sample fixture and render the
            HTML viewer (no browser, no Playwright needed).
  capture   Live-capture a page with Playwright (optional dependency).
  view      Render a bundle directory to a standalone HTML report.
  export    Pack a bundle into a shareable zip (requires confirmation).
  import    Unpack and validate an exported bundle zip.
  validate  Check a bundle directory for structural problems.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .bundle import BundleError, export_bundle, import_bundle, load_bundle, validate_bundle
from .redaction import RedactionRules
from .viewer import render_to_file

FIXTURE_BUNDLE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_bundle"
DEMO_PAGE = Path(__file__).resolve().parent.parent / "demo" / "index.html"


def _rules_from_args(args: argparse.Namespace) -> RedactionRules:
    return RedactionRules(
        extra_param_names=args.redact_param or [],
        dom_selectors=args.redact_selector or [],
        redact_emails=not args.no_redact_emails,
        redact_tokens=not args.no_redact_tokens,
    )


def cmd_demo(args: argparse.Namespace) -> int:
    if not FIXTURE_BUNDLE.is_dir():
        print(f"error: sample fixture bundle not found at {FIXTURE_BUNDLE}", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="bugbundle-demo-"))
    bundle_dir = work / "sample_bundle"
    shutil.copytree(FIXTURE_BUNDLE, bundle_dir)
    warnings = validate_bundle(bundle_dir)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    out_html = Path(args.out or work / "report.html")
    try:
        render_to_file(bundle_dir, out_html)
    except (BundleError, OSError) as exc:
        print(f"error: cannot write report: {exc}", file=sys.stderr)
        return 1
    bundle = load_bundle(bundle_dir)
    failed = [r for r in bundle.network if r.get("failed") or (r.get("status") or 0) >= 400]
    errors = [e for e in bundle.console if e.get("level") in ("error", "pageerror")]
    print(f"Loaded sample bundle: {bundle_dir}")
    print(f"  url: {bundle.manifest.get('url')}")
    print(f"  viewport: {bundle.manifest.get('viewport')}")
    print(f"  steps: {len(bundle.steps)}, console entries: {len(bundle.console)} "
          f"({len(errors)} errors), network: {len(bundle.network)} ({len(failed)} failed)")
    print(f"HTML report written to: {out_html}")
    print(f"Open it in a browser to inspect every artifact. Demo page (for live capture): {DEMO_PAGE}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from .capture import capture  # deferred: playwright is optional

    try:
        root = capture(
            args.url,
            Path(args.out),
            rules=_rules_from_args(args),
            headless=args.headless,
        )
    except (RuntimeError, BundleError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # e.g. playwright's browser binary missing or the page failing to
        # load: report a single actionable line instead of a traceback.
        print(f"error: capture failed: {exc}", file=sys.stderr)
        return 1
    print(f"Bundle written to: {root}")
    print("Next: inspect it with `python -m bugbundle view <dir>` before sharing.")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else Path(args.bundle).with_suffix(".html")
    try:
        render_to_file(Path(args.bundle), out)
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"HTML report written to: {out}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle)
    try:
        bundle = load_bundle(bundle_dir)
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.yes:
        print("You are about to share a bug-report bundle containing:")
        print(f"  {len(bundle.steps)} recorded steps, {len(bundle.console)} console entries,")
        print(f"  {len(bundle.network)} network requests, "
              f"{len(bundle.screenshots)} screenshots, DOM snapshot: "
              f"{'yes' if bundle.dom_snapshot else 'no'}")
        print("Redaction has been applied, but YOU are responsible for reviewing")
        print("every artifact first (`python -m bugbundle view <dir>`).")
        try:
            answer = input("Type 'share' to confirm export: ").strip().lower()
        except EOFError:
            print("error: could not read confirmation (stdin closed); "
                  "use --yes for scripted exports", file=sys.stderr)
            return 2
        if answer != "share":
            print("Export cancelled.")
            return 2
    try:
        out_zip = export_bundle(bundle_dir, Path(args.out), confirm=True)
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
        return 1
    print(f"Bundle exported to: {out_zip}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    try:
        root = import_bundle(Path(args.archive), Path(args.out))
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Bundle imported and validated at: {root}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        warnings = validate_bundle(Path(args.bundle))
    except BundleError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"warning: {w}")
    print("Bundle is valid." + (f" ({len(warnings)} warning(s))" if warnings else ""))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bugbundle",
        description="Portable, redacted browser bug-report bundles.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_redaction_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--redact-param", action="append",
                       help="extra URL query parameter name to redact (repeatable)")
        p.add_argument("--redact-selector", action="append",
                       help="DOM region to blank out: #id, .class or tag (repeatable)")
        p.add_argument("--no-redact-emails", action="store_true",
                       help="do not redact email addresses in text")
        p.add_argument("--no-redact-tokens", action="store_true",
                       help="do not redact bearer/JWT-like tokens in text")

    p = sub.add_parser("demo", help="render the bundled sample fixture (no browser needed)")
    p.add_argument("--out", help="output HTML path (default: alongside temp copy)")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("capture", help="live-capture a page (requires playwright)")
    p.add_argument("url", help="page URL, e.g. file:///path/to/demo/index.html")
    p.add_argument("--out", required=True, help="output bundle directory (must not exist)")
    p.add_argument("--headless", action="store_true", help="run browser headless")
    add_redaction_opts(p)
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("view", help="render a bundle directory to a standalone HTML report")
    p.add_argument("bundle", help="bundle directory")
    p.add_argument("--out", help="output HTML path (default: <bundle>.html)")
    p.set_defaults(func=cmd_view)

    p = sub.add_parser("export", help="pack a bundle into a shareable zip (asks to confirm)")
    p.add_argument("bundle", help="bundle directory")
    p.add_argument("--out", required=True, help="output zip path")
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive confirmation (scripts only)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="unpack and validate an exported bundle zip")
    p.add_argument("archive", help=".bugbundle.zip file")
    p.add_argument("--out", required=True, help="directory to unpack into")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("validate", help="check a bundle directory")
    p.add_argument("bundle", help="bundle directory")
    p.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
