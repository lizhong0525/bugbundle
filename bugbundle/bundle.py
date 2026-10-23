"""Bundle folder format: creation, validation, export (zip) and import.

A bundle is a plain directory:

    manifest.json     format version, page URL, viewport, timestamps
    steps.json        recorded user steps
    console.json      console messages and page errors
    network.json      network requests incl. failures
    dom_snapshot.html redacted DOM snapshot (optional)
    screenshots/      PNG/JPEG artifacts referenced by steps

Export packs the folder into a single .zip (`.bugbundle.zip`) so it can be
shared; import unpacks and validates it. Export requires explicit
confirmation unless confirm=True is passed by the caller.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import BUNDLE_FORMAT

REQUIRED_FILES = ("manifest.json", "steps.json", "console.json", "network.json")


class BundleError(Exception):
    """Raised for malformed, missing, or unsupported bundles."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Bundle:
    """An in-memory view of a bundle directory."""

    root: Path
    manifest: dict
    steps: list[dict]
    console: list[dict]
    network: list[dict]

    @property
    def dom_snapshot(self) -> str | None:
        path = self.root / "dom_snapshot.html"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    @property
    def screenshots(self) -> list[Path]:
        shot_dir = self.root / "screenshots"
        if not shot_dir.is_dir():
            return []
        return sorted(p for p in shot_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})


def new_manifest(url: str, viewport: dict, user_agent: str = "") -> dict:
    return {
        "format": BUNDLE_FORMAT,
        "created_at": utc_now_iso(),
        "url": url,
        "viewport": viewport,
        "user_agent": user_agent,
        "capture_indicator": True,
        "passwords_recorded": False,
        "hidden_inputs_recorded": False,
    }


def write_bundle(
    root: Path,
    manifest: dict,
    steps: list[dict],
    console: list[dict],
    network: list[dict],
    dom_snapshot: str | None = None,
) -> Path:
    """Write a bundle directory. `root` must not already exist."""
    root = Path(root)
    if root.exists():
        raise BundleError(f"Bundle directory already exists: {root}")
    (root / "screenshots").mkdir(parents=True)
    manifest.setdefault("format", BUNDLE_FORMAT)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "steps.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")
    (root / "console.json").write_text(json.dumps(console, indent=2), encoding="utf-8")
    (root / "network.json").write_text(json.dumps(network, indent=2), encoding="utf-8")
    if dom_snapshot is not None:
        (root / "dom_snapshot.html").write_text(dom_snapshot, encoding="utf-8")
    return root


def _read_json(path: Path, expect: type) -> object:
    if not path.is_file():
        raise BundleError(f"Missing required file: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BundleError(f"Malformed JSON in {path.name}: {exc}") from exc
    if not isinstance(data, expect):
        raise BundleError(f"{path.name} must contain a JSON {expect.__name__}")
    return data


def validate_bundle(root: Path) -> list[str]:
    """Validate a bundle directory. Returns a list of non-fatal warnings.

    Raises BundleError on structural problems (missing/malformed files,
    unsupported format version).
    """
    root = Path(root)
    if not root.is_dir():
        raise BundleError(f"Not a bundle directory: {root}")
    manifest = _read_json(root / "manifest.json", dict)
    fmt = manifest.get("format")
    if fmt != BUNDLE_FORMAT:
        raise BundleError(f"Unsupported bundle format: {fmt!r} (expected {BUNDLE_FORMAT!r})")
    for name in ("steps.json", "console.json", "network.json"):
        _read_json(root / name, list)
    warnings: list[str] = []
    if "url" not in manifest:
        warnings.append("manifest.json has no 'url' field")
    if "viewport" not in manifest:
        warnings.append("manifest.json has no 'viewport' field")
    shots = root / "screenshots"
    if shots.is_dir():
        for step in _read_json(root / "steps.json", list):
            shot = step.get("screenshot")
            if shot and not (shots / shot).is_file():
                warnings.append(f"Step references missing screenshot: {shot}")
    return warnings


def load_bundle(root: Path) -> Bundle:
    """Validate and load a bundle directory into memory."""
    root = Path(root)
    validate_bundle(root)
    return Bundle(
        root=root,
        manifest=_read_json(root / "manifest.json", dict),
        steps=_read_json(root / "steps.json", list),
        console=_read_json(root / "console.json", list),
        network=_read_json(root / "network.json", list),
    )


def export_bundle(root: Path, out_zip: Path, confirm: bool = False) -> Path:
    """Pack a bundle directory into a zip file.

    Sharing a bundle is a deliberate action: callers must pass confirm=True
    (the CLI obtains it interactively). Raises BundleError otherwise.
    """
    root = Path(root)
    validate_bundle(root)  # never export something we could not load back
    if not confirm:
        raise BundleError(
            "Export refused: bundle contains recorded browsing data. "
            "Review every artifact, then confirm explicitly to share."
        )
    out_zip = Path(out_zip)
    name = out_zip.name
    if name.endswith(".bugbundle.zip"):
        pass
    elif name.endswith(".zip"):
        out_zip = out_zip.with_name(name[: -len(".zip")] + ".bugbundle.zip")
    else:
        out_zip = out_zip.with_name(name + ".bugbundle.zip")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root))
    return out_zip


def import_bundle(zip_path: Path, dest_dir: Path) -> Path:
    """Unpack an exported bundle zip into dest_dir and validate it.

    Returns the bundle directory. Refuses path-traversal entries.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise BundleError(f"Bundle archive not found: {zip_path}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest_dir.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                target = (dest_resolved / info.filename).resolve()
                if not str(target).startswith(str(dest_resolved)):
                    raise BundleError(f"Unsafe path in archive: {info.filename!r}")
            zf.extractall(dest_resolved)
    except zipfile.BadZipFile as exc:
        raise BundleError(f"Not a valid zip archive: {zip_path}") from exc
    # The archive may contain the bundle flat or nested under one directory.
    if (dest_resolved / "manifest.json").is_file():
        bundle_root = dest_resolved
    else:
        candidates = [d for d in dest_resolved.iterdir() if d.is_dir() and (d / "manifest.json").is_file()]
        if not candidates:
            raise BundleError("Archive does not contain a valid bundle (no manifest.json)")
        bundle_root = candidates[0]
    validate_bundle(bundle_root)
    return bundle_root
