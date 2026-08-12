#!/usr/bin/env python3
"""Validate the Git control plane and list every referenced TOS object."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BINARY_SUFFIXES = {
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
RELEASE_SUFFIXES = BINARY_SUFFIXES | {".jpeg", ".jpg", ".png"}
TOS_DOWNLOAD_HOSTS = {
    "software.xiao-r.com",
    "software2.tos-cn-beijing.volces.com",
}


def fail(message: str) -> None:
    raise ValueError(message)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode() for item in result.stdout.split(b"\0") if item]


def normalize_object(value: str, base: str = "") -> str | None:
    value = value.strip().strip("'\"")
    if value.startswith("//"):
        parsed = urlparse(f"https:{value}")
        if parsed.hostname not in TOS_DOWNLOAD_HOSTS:
            return None
        return parsed.path.lstrip("/")
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.hostname not in TOS_DOWNLOAD_HOSTS:
            return None
        return parsed.path.lstrip("/")
    if value.startswith("./"):
        value = value[2:]
    return f"{base}{value}".lstrip("/")


def data_objects() -> tuple[set[str], list[dict]]:
    path = ROOT / "data.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid data.json: {exc}")
    if not isinstance(data, list):
        fail("data.json must contain a top-level list")

    objects: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            fail("every data.json entry must be an object")
        for field in ("link", "oldVersion"):
            values = entry.get(field, [])
            if not isinstance(values, list):
                fail(f"data.json field {field} must be a list")
            for value in values:
                key = normalize_object(str(value))
                if key:
                    objects.add(key)
        for tool in entry.get("tools", []):
            if isinstance(tool, dict) and tool.get("file_path"):
                key = normalize_object(str(tool["file_path"]))
                if key:
                    objects.add(key)
    return objects, data


def yaml_urls(path: Path, base: str = "") -> set[str]:
    objects: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:url|path):\s*(.+?)\s*$", line)
        if not match:
            continue
        key = normalize_object(match.group(1), base)
        if key:
            objects.add(key)
    return objects


def referenced_objects() -> tuple[set[str], list[dict]]:
    objects, data = data_objects()
    objects |= yaml_urls(ROOT / "update/software.yaml")
    objects |= yaml_urls(ROOT / "firmware/mxbit/version.yaml", "firmware/mxbit/")
    objects |= yaml_urls(ROOT / "software/pc/latest.yml", "software/pc/")
    objects |= yaml_urls(
        ROOT / "software/pc/moxin/latest.yml", "software/pc/moxin/"
    )
    return objects, data


def validate() -> set[str]:
    binaries = [
        path for path in tracked_files() if Path(path).suffix.lower() in BINARY_SUFFIXES
    ]
    if binaries:
        fail("release binaries are tracked by Git:\n  " + "\n  ".join(binaries))

    objects, data = referenced_objects()
    invalid = [key for key in sorted(objects) if Path(key).suffix.lower() not in RELEASE_SUFFIXES]
    if invalid:
        fail("unsupported release object references:\n  " + "\n  ".join(invalid))

    xrblock = [
        entry
        for entry in data
        if entry.get("name", {}).get("en") == "XRBlock Scratch3.0 Software"
    ]
    if len(xrblock) != 1:
        fail("data.json must contain exactly one XRBlock entry")
    entry = xrblock[0]
    if entry.get("version") != "v2.2.6" or entry.get("link") != [
        "https://software2.tos-cn-beijing.volces.com/software/pc/XR Block v2.2.6.exe"
    ]:
        fail("XRBlock website release must point to v2.2.6")

    omnimind = [key for key in objects if "omnimind" in key.lower()]
    if omnimind:
        fail("retired OmniMind objects must not be referenced")

    return objects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--print-objects",
        action="store_true",
        help="print normalized TOS object keys after validation",
    )
    args = parser.parse_args()
    try:
        objects = validate()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1

    if args.print_objects:
        print("\n".join(sorted(objects)))
    else:
        print(f"release validation passed: {len(objects)} referenced TOS objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
