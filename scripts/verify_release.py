from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

FORBIDDEN = {"__pycache__", ".pytest_cache", ".ruff_cache", "build", ".git"}
FORBIDDEN_RUNTIME = {".instance-nonce", "config.json", "timers.jsonl", "saiplan.log"}
SOURCE_REQUIRED = {
    "src/saiplan/__init__.py",
    "tests/test_board.py",
    "themes/goldenvintage.json",
    "scripts/package_source.ps1",
    "scripts/package_portable.ps1",
    "scripts/verify_release.py",
    "bootstrap-build-env.ps1",
    "build_windows.ps1",
    "requirements-build.lock",
    "README.md",
    "CHANGELOG.md",
    "VERSION",
    "pyproject.toml",
}


def files_under(root: Path, suffix: str) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob(f"*{suffix}")
        if path.is_file()
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity(root: Path) -> str:
    paths = list((root / "src").rglob("*.py"))
    paths.extend(
        root / name
        for name in (
            "main.py",
            "pyproject.toml",
            "VERSION",
            "build_windows.ps1",
            "bootstrap-build-env.ps1",
            "requirements-build.lock",
        )
    )
    payload = "".join(
        f"{path.relative_to(root).as_posix()}\0{digest(path)}\n"
        for path in sorted(paths)
        if path.is_file()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reject_junk(root: Path) -> None:
    bad = [
        path
        for path in root.rglob("*")
        if path.name in FORBIDDEN
        or path.name in FORBIDDEN_RUNTIME
        or path.suffix in {".pyc", ".log"}
    ]
    if bad:
        raise SystemExit("generated junk present: " + ", ".join(str(path) for path in bad[:10]))


def verify_source(root: Path) -> None:
    reject_junk(root)
    missing = sorted(path for path in SOURCE_REQUIRED if not (root / path).is_file())
    if missing:
        raise SystemExit("source package missing: " + ", ".join(missing))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    package = (root / "src/saiplan/__init__.py").read_text(encoding="utf-8")
    if f'version = "{version}"' not in pyproject or f'__version__ = "{version}"' not in package:
        raise SystemExit("VERSION, pyproject.toml and package version differ")
    if not files_under(root / "themes", ".json") or not files_under(root / "sounds", ".wav"):
        raise SystemExit("source assets missing")
    print("source: required files, versions, assets and junk gate verified")


def verify_portable(source: Path, root: Path, write_manifest: bool) -> None:
    exe = root / "SAIPLAN.exe"
    if not exe.is_file():
        raise SystemExit(f"missing executable: {exe}")
    identity_path = root / "BUILD-SOURCE.sha256"
    expected_identity = source_identity(source)
    if (
        not identity_path.is_file()
        or identity_path.read_text(encoding="ascii").strip() != expected_identity
    ):
        raise SystemExit("portable executable is stale for current source identity")
    for directory, suffix in (("themes", ".json"), ("sounds", ".wav")):
        expected = files_under(source / directory, suffix)
        actual = files_under(root / directory, suffix)
        if expected.keys() != actual.keys():
            raise SystemExit(f"{directory} manifest differs from source")
        mismatched = [name for name in expected if digest(expected[name]) != digest(actual[name])]
        if mismatched:
            raise SystemExit(f"{directory} hashes differ: {mismatched[:5]}")
        print(f"{directory}: {len(actual)} files")
    reject_junk(root)
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "MANIFEST.sha256":
            continue
        entries.append(f"{digest(path)}  {path.relative_to(root).as_posix()}")
    manifest = "\n".join(entries) + "\n"
    manifest_path = root / "MANIFEST.sha256"
    if write_manifest:
        manifest_path.write_text(manifest, encoding="utf-8", newline="\n")
    elif not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != manifest:
        raise SystemExit("MANIFEST.sha256 missing or stale")
    print(f"portable: {len(entries)} files; manifest verified")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("portable", "source", "identity"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.mode == "identity":
        if args.output is None:
            parser.error("identity mode requires --output")
        args.output.write_text(source_identity(root) + "\n", encoding="ascii")
        print(f"source identity: {source_identity(root)}")
    elif args.mode == "source":
        verify_source(root)
    else:
        if args.source is None:
            parser.error("portable mode requires --source")
        verify_portable(args.source.resolve(), root, args.write_manifest)


if __name__ == "__main__":
    main()
