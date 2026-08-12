#!/usr/bin/env python3
"""Upload local binaries to a GitHub Draft Release and write a public manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "releases"
MAX_ASSET_SIZE = 2 * 1024 * 1024 * 1024
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
ALLOWED_SUFFIXES = {
    ".aab",
    ".apk",
    ".bin",
    ".blockmap",
    ".dmg",
    ".exe",
    ".hex",
    ".msi",
    ".zip",
}
ALLOWED_TOS_PREFIXES = ("software/", "firmware/")
GH_CLI = os.environ.get("XIAOR_GH", "gh")


class ReleaseError(RuntimeError):
    pass


def run_gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GH_CLI, *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_asset_name(filename: str) -> str:
    """Return a deterministic GitHub-safe name while TOS keeps its original key."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", ".", filename).strip(".")
    suffix = Path(filename).suffix.lower()
    if not safe or Path(safe).suffix.lower() != suffix:
        stem = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
        safe = f"asset-{stem}{suffix}"
    return safe


def parse_asset(value: str) -> tuple[Path, str, str]:
    if "=" not in value:
        raise ReleaseError("--asset must use LOCAL_FILE=TOS_KEY")
    source_text, tos_key = value.split("=", 1)
    source = Path(source_text).expanduser().resolve()
    key = PurePosixPath(tos_key)

    if not source.is_file():
        raise ReleaseError(f"asset is not a regular file: {source}")
    if source.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ReleaseError(f"unsupported release asset type: {source.name}")
    if source.stat().st_size <= 0 or source.stat().st_size >= MAX_ASSET_SIZE:
        raise ReleaseError(f"asset must be non-empty and smaller than 2 GiB: {source.name}")
    if key.is_absolute() or ".." in key.parts:
        raise ReleaseError(f"unsafe TOS key: {tos_key}")
    normalized_key = key.as_posix()
    if not normalized_key.startswith(ALLOWED_TOS_PREFIXES):
        raise ReleaseError(f"TOS key must start with software/ or firmware/: {tos_key}")
    if key.name != source.name:
        raise ReleaseError(
            f"local filename and TOS key basename must match: {source.name} != {key.name}"
        )
    return source, normalized_key, release_asset_name(source.name)


def release_info(repository: str, tag: str) -> dict | None:
    result = run_gh(
        "release",
        "view",
        tag,
        "--repo",
        repository,
        "--json",
        "isDraft,name,tagName,assets",
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def ensure_draft_release(repository: str, tag: str, title: str) -> dict:
    info = release_info(repository, tag)
    if info is None:
        run_gh(
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--draft",
            "--target",
            "master",
            "--title",
            title,
            "--notes",
            "Prepared by scripts/prepare_release.py; publication requires reviewed master.",
        )
        info = release_info(repository, tag)
    if not info or not info.get("isDraft"):
        raise ReleaseError(f"release {tag} exists and is not a draft")
    return info


def verify_existing_asset(asset: dict, expected_size: int, expected_sha: str) -> None:
    if (
        asset.get("state") != "uploaded"
        or asset.get("size") != expected_size
        or asset.get("digest") != f"sha256:{expected_sha}"
    ):
        raise ReleaseError(
            f"draft asset {asset.get('name')} already exists with different or incomplete "
            "content; refusing overwrite"
        )


def load_manifest(path: Path, tag: str, title: str) -> dict:
    if not path.exists():
        return {
            "schema_version": 1,
            "tag": tag,
            "title": title,
            "target_commitish": "master",
            "assets": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("tag") != tag:
        raise ReleaseError(f"existing manifest tag mismatch: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a GitHub Draft Release without committing binaries to Git"
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--asset",
        action="append",
        required=True,
        metavar="LOCAL_FILE=TOS_KEY",
        help="repeat for every architecture/platform asset",
    )
    args = parser.parse_args()

    try:
        if not TAG_RE.fullmatch(args.tag):
            raise ReleaseError(
                "tag must be 3-128 lowercase letters, digits, dots, underscores or hyphens"
            )
        repository_result = run_gh("repo", "view", "--json", "nameWithOwner")
        repository = json.loads(repository_result.stdout)["nameWithOwner"]
        assets = [parse_asset(value) for value in args.asset]
        if len({name for _, _, name in assets}) != len(assets):
            raise ReleaseError("duplicate normalized GitHub Release asset name")
        if len({key for _, key, _ in assets}) != len(assets):
            raise ReleaseError("duplicate TOS key")

        info = ensure_draft_release(repository, args.tag, args.title)
        existing_assets = {asset["name"]: asset for asset in info.get("assets", [])}
        prepared: list[dict] = []
        for source, tos_key, asset_name in assets:
            digest = sha256(source)
            if asset_name in existing_assets:
                verify_existing_asset(
                    existing_assets[asset_name], source.stat().st_size, digest
                )
                print(f"verified existing draft asset: {asset_name}")
            else:
                if asset_name == source.name:
                    upload_path = source
                    run_gh(
                        "release",
                        "upload",
                        args.tag,
                        str(upload_path),
                        "--repo",
                        repository,
                    )
                else:
                    with tempfile.TemporaryDirectory(
                        prefix="xiaor-release-name-", dir=source.parent
                    ) as directory:
                        upload_path = Path(directory) / asset_name
                        try:
                            os.link(source, upload_path)
                        except OSError:
                            shutil.copyfile(source, upload_path)
                        run_gh(
                            "release",
                            "upload",
                            args.tag,
                            str(upload_path),
                            "--repo",
                            repository,
                        )
                print(f"uploaded draft asset: {asset_name}")
            prepared.append(
                {
                    "name": asset_name,
                    "tos_key": tos_key,
                    "size": source.stat().st_size,
                    "sha256": digest,
                }
            )

        MANIFEST_DIR.mkdir(exist_ok=True)
        manifest_path = MANIFEST_DIR / f"{args.tag}.json"
        manifest = load_manifest(manifest_path, args.tag, args.title)
        merged = {asset["name"]: asset for asset in manifest.get("assets", [])}
        for asset in prepared:
            current = merged.get(asset["name"])
            if current and current != asset:
                raise ReleaseError(
                    f"manifest already declares different content for {asset['name']}"
                )
            merged[asset["name"]] = asset
        manifest["title"] = args.title
        manifest["assets"] = sorted(merged.values(), key=lambda item: item["name"])
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote public manifest: {manifest_path.relative_to(ROOT)}")
        print("next: update data.json/updater manifests, validate, commit, push and open a PR")
        return 0
    except (json.JSONDecodeError, OSError, ReleaseError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        print(f"release preparation failed: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
