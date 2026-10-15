#!/usr/bin/env python3
"""Validate the Git control plane and list every referenced TOS object."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from pathlib import PurePosixPath
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
    ".xrup",
    ".zip",
}
RELEASE_SUFFIXES = BINARY_SUFFIXES | {".jpeg", ".jpg", ".png"}
PUBLIC_DOWNLOAD_BASE_URL = "https://software.xiao-r.com/"
TOS_DOWNLOAD_HOSTS = {"software.xiao-r.com"}
MAX_RELEASE_ASSET_SIZE = 2 * 1024 * 1024 * 1024
RELEASE_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
SENSITIVE_SUFFIXES = {".env", ".key", ".p8", ".p12", ".pem"}
SENSITIVE_NAMES = {
    ".env",
    ".tosutilconfig",
    "credentials",
    "hosts.yml",
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
        match = re.match(r"^\s*(?:-\s*)?(?:url|path):\s*(.+?)\s*$", line)
        if not match:
            continue
        key = normalize_object(match.group(1), base)
        if key:
            objects.add(key)
    return objects


def electron_updater_objects(path: Path, base: str) -> set[str]:
    """Return updater packages plus same-channel differential blockmaps.

    A feed may reuse an immutable installer already published by another
    controlled channel.  electron-updater falls back to the SHA512-verified
    full installer when that cross-channel URL has no adjacent blockmap.
    """
    objects = yaml_urls(path, base)
    blockmaps = {
        f"{key}.blockmap"
        for key in objects
        if key.startswith(base)
        and Path(key).suffix.lower() in {".dmg", ".exe", ".zip"}
    }
    return objects | blockmaps


def referenced_objects() -> tuple[set[str], list[dict]]:
    objects, data = data_objects()
    objects |= yaml_urls(ROOT / "update/software.yaml")
    objects |= yaml_urls(ROOT / "firmware/mxbit/version.yaml", "firmware/mxbit/")
    objects |= yaml_urls(ROOT / "firmware/xr-base/version.yaml", "firmware/xr-base/")
    objects |= yaml_urls(
        ROOT / "firmware/xr-car-tail/version.yaml", "firmware/xr-car-tail/"
    )
    objects |= yaml_urls(
        ROOT / "firmware/xr-aud-01/version.yaml", "firmware/xr-aud-01/"
    )
    objects |= yaml_urls(
        ROOT / "firmware/xr-zero-imu/version.yaml", "firmware/xr-zero-imu/"
    )
    objects |= yaml_urls(
        ROOT / "firmware/xr-zero-imu/production.yaml", "firmware/xr-zero-imu/"
    )
    objects |= yaml_urls(ROOT / "software/pc/latest.yml", "software/pc/")
    objects |= yaml_urls(
        ROOT / "software/pc/moxin/latest.yml", "software/pc/moxin/"
    )
    objects |= electron_updater_objects(
        ROOT / "ota/xr-studio/latest.yml", "ota/xr-studio/"
    )
    objects |= electron_updater_objects(
        ROOT / "ota/xr-studio/latest-mac.yml", "ota/xr-studio/"
    )
    return objects, data


def validate_release_manifests() -> tuple[int, set[str]]:
    manifest_dir = ROOT / "releases"
    seen_tags: set[str] = set()
    seen_tos_keys: set[str] = set()
    count = 0
    manifest_keys: set[str] = set()
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"invalid release manifest {path.relative_to(ROOT)}: {exc}")
        if not isinstance(manifest, dict):
            fail(f"release manifest must be an object: {path.relative_to(ROOT)}")
        if set(manifest) != {
            "schema_version",
            "tag",
            "title",
            "target_commitish",
            "assets",
        }:
            fail(f"unexpected fields in release manifest: {path.relative_to(ROOT)}")
        tag = manifest.get("tag")
        if (
            manifest.get("schema_version") != 1
            or not isinstance(tag, str)
            or not RELEASE_TAG_RE.fullmatch(tag)
            or path.stem != tag
            or tag in seen_tags
        ):
            fail(f"invalid or duplicate release tag: {path.relative_to(ROOT)}")
        if manifest.get("target_commitish") != "master":
            fail(f"release target must be master: {path.relative_to(ROOT)}")
        if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
            fail(f"release title must not be empty: {path.relative_to(ROOT)}")
        assets = manifest.get("assets")
        if not isinstance(assets, list) or not assets:
            fail(f"release manifest must contain assets: {path.relative_to(ROOT)}")

        seen_names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, dict) or set(asset) != {
                "name",
                "tos_key",
                "size",
                "sha256",
            }:
                fail(f"invalid asset fields in {path.relative_to(ROOT)}")
            name = asset.get("name")
            tos_key = asset.get("tos_key")
            size = asset.get("size")
            digest = asset.get("sha256")
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or Path(name).suffix.lower() not in BINARY_SUFFIXES
                or re.search(r"[\x00-\x1f*?\[\]]", name)
                or name in seen_names
            ):
                fail(f"invalid or duplicate asset name in {path.relative_to(ROOT)}")
            key = PurePosixPath(tos_key) if isinstance(tos_key, str) else None
            if (
                key is None
                or key.is_absolute()
                or ".." in key.parts
                or re.search(r"[\x00-\x1f]", key.as_posix())
                or not key.as_posix().startswith(("software/", "firmware/", "ota/"))
                or Path(key.name).suffix.lower() != Path(name).suffix.lower()
                or key.as_posix() in seen_tos_keys
            ):
                fail(f"invalid or duplicate TOS key in {path.relative_to(ROOT)}")
            if not isinstance(size, int) or size <= 0 or size >= MAX_RELEASE_ASSET_SIZE:
                fail(f"asset must be non-empty and smaller than 2 GiB: {name}")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                fail(f"invalid SHA256 for release asset: {name}")
            seen_names.add(name)
            seen_tos_keys.add(key.as_posix())
            manifest_keys.add(key.as_posix())
            count += 1
        seen_tags.add(tag)
    return count, manifest_keys


def validate_superseded_assets(
    manifest_keys: set[str], referenced_keys: set[str]
) -> set[str]:
    path = ROOT / "releases/audit/superseded-assets.json"
    if not path.exists():
        return set()
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid superseded asset registry: {exc}")
    if not isinstance(records, list):
        fail("superseded asset registry must contain a top-level list")

    superseded: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "tos_key",
            "replacement_tos_key",
            "reason",
        }:
            fail("invalid superseded asset registry entry")
        old_key = record.get("tos_key")
        replacement = record.get("replacement_tos_key")
        reason = record.get("reason")
        if (
            not isinstance(old_key, str)
            or not isinstance(replacement, str)
            or not isinstance(reason, str)
            or not reason.strip()
            or old_key == replacement
            or old_key in superseded
            or old_key not in manifest_keys
            or replacement not in manifest_keys
            or old_key in referenced_keys
            or replacement not in referenced_keys
        ):
            fail(f"invalid superseded asset mapping: {old_key} -> {replacement}")
        superseded.add(old_key)
    return superseded


def validate() -> set[str]:
    tracked = tracked_files()
    binaries = [path for path in tracked if Path(path).suffix.lower() in BINARY_SUFFIXES]
    if binaries:
        fail("release binaries are tracked by Git:\n  " + "\n  ".join(binaries))

    sensitive = [
        path
        for path in tracked
        if Path(path).suffix.lower() in SENSITIVE_SUFFIXES
        or Path(path).name.lower() in SENSITIVE_NAMES
        or Path(path).name.lower().startswith(".env.")
        or ".ssh" in Path(path).parts
    ]
    if sensitive:
        fail("sensitive files are tracked by Git:\n  " + "\n  ".join(sensitive))

    objects, data = referenced_objects()
    _, manifest_keys = validate_release_manifests()
    superseded = validate_superseded_assets(manifest_keys, objects)
    orphaned = sorted(manifest_keys - objects - superseded)
    if orphaned:
        fail("release assets are not referenced by public metadata:\n  " + "\n  ".join(orphaned))
    invalid = [key for key in sorted(objects) if Path(key).suffix.lower() not in RELEASE_SUFFIXES]
    if invalid:
        fail("unsupported release object references:\n  " + "\n  ".join(invalid))

    index = (ROOT / "index.html").read_text(encoding="utf-8")
    style_digest = hashlib.sha256((ROOT / "style.css").read_bytes()).hexdigest()[:12]
    expected_style_href = f'href="style.css?v={style_digest}"'
    if expected_style_href not in index:
        fail(
            "index.html stylesheet cache version must match the first 12 "
            "characters of the style.css SHA256"
        )
    expected_base = f"const RELEASE_BASE_URL = '{PUBLIC_DOWNLOAD_BASE_URL}';"
    if expected_base not in index:
        fail("index.html must use the HTTPS custom domain as RELEASE_BASE_URL")
    if "software2.tos-cn-beijing.volces.com" in index:
        fail("index.html must not expose the raw TOS bucket domain")

    xrblock = [
        entry
        for entry in data
        if entry.get("name", {}).get("en") == "XRBlock Scratch3.0 Software"
    ]
    if len(xrblock) != 1:
        fail("data.json must contain exactly one XRBlock entry")
    entry = xrblock[0]
    if entry.get("version") != "v2.3.3" or entry.get("link") != [
        "software/pc/XR Block v2.3.3.exe"
    ]:
        fail("XRBlock website release must point to v2.3.3")

    omnimind = [key for key in objects if "omnimind" in key.lower()]
    if omnimind:
        fail("retired OmniMind objects must not be referenced")

    xr_studio = [
        entry for entry in data if entry.get("name", {}).get("en") == "XR Studio"
    ]
    expected_xr_studio = {
        "windows": {
            "version": "v1.1.4",
            "link": [
                "https://software.xiao-r.com/software/pc/"
                "xr-studio-1.1.4-win-x64.exe",
                "https://software.xiao-r.com/software/pc/"
                "xr-studio-1.1.4-win-x64.zip",
            ],
            "button_en": ["Windows x64 Installer", "Windows x64 Portable ZIP"],
            "button_zh": ["Windows x64 安装版", "Windows x64 便携 ZIP"],
        },
        "mac": {
            "version": "v1.1.3",
            "link": [
                "https://software.xiao-r.com/software/pc/"
                "xr-studio-1.1.3-mac-arm64.dmg"
            ],
            "button_en": ["macOS Apple Silicon"],
            "button_zh": ["macOS Apple Silicon"],
        },
    }
    if len(xr_studio) != 2:
        fail("data.json must contain exactly two XR Studio platform entries")
    for entry in xr_studio:
        platform = entry.get("platform")
        expected = expected_xr_studio.get(platform)
        if (
            expected is None
            or entry.get("logoSrc") != "./software/image/xr-studio.png"
            or entry.get("version") != expected["version"]
            or entry.get("link") != expected["link"]
            or entry.get("btnNames", {}).get("en") != expected["button_en"]
            or entry.get("btnNames", {}).get("zh") != expected["button_zh"]
            or entry.get("platformVersions")
            != {"windows": "v1.1.4", "mac": "v1.1.3"}
        ):
            fail(f"invalid XR Studio data.json entry for platform: {platform}")
        if platform == "mac" and (
            entry.get("oldVersion") != [
                "https://software.xiao-r.com/software/pc/xr-studio-1.1.2-mac-arm64.dmg",
                "https://software.xiao-r.com/software/pc/xr-studio-1.0.1-mac-arm64.dmg",
            ]
            or "preview" not in entry.get("desc", {}).get("en", "").lower()
            or "客户试用" not in entry.get("desc", {}).get("zh", "")
        ):
            fail("XR Studio Mac preview requires bilingual labels and the 1.1.2 rollback")
        if platform == "windows":
            if entry.get("oldVersion") != [
                "https://software.xiao-r.com/software/pc/xr-studio-1.1.3-win-x64.exe",
                "https://software.xiao-r.com/software/pc/xr-studio-1.1.3-win-x64.zip",
                "https://software.xiao-r.com/software/pc/xr-studio-1.1.2-win-x64.exe",
                "https://software.xiao-r.com/software/pc/xr-studio-1.1.2-win-x64.zip",
                "https://software.xiao-r.com/software/pc/xr-studio-1.0.1-win-x64.exe",
                "https://software.xiao-r.com/software/pc/xr-studio-1.0.1-win-x64.zip",
            ]:
                fail("XR Studio Windows preview requires the 1.1.3 rollback")
            required_notices = {
                "en": ("Preview 1.1.4", "XR-BASE", "APP-only local/online OTA",
                       "strict product/identity/SHA/CRC validation",
                       "post-reboot same-device/version confirmation",
                       "not Authenticode signed", "Public ASAR", "native serial",
                       "real HTTPS APP OTA", "operator reported", "GUI OTA",
                       "complete power-cycle", "Public query",
                       "installer installation process was not independently tested",
                       "directory build", "Portable ZIP", "Internal authorization/configuration",
                       "PY32 worker/factory firmware", "device backups/logs",
                       "Stable auto-update remains at 1.0.1"),
                "zh": ("1.1.4 客户试用", "XR-BASE", "APP-only 本地/在线 OTA",
                       "严格校验产品、身份、SHA/CRC", "重启后再确认同一设备和目标版本",
                       "未做 Authenticode 签名", "Public ASAR", "原生串口",
                       "真实 HTTPS APP OTA", "操作者确认", "GUI OTA",
                       "完全断电重启", "Public 查询", "安装器安装过程未单独测试",
                       "GUI 验收使用目录包", "ZIP", "Internal 授权/配置",
                       "PY32 worker/工厂固件", "设备备份/日志",
                       "稳定自更新保持 1.0.1"),
            }
            for language, notices in required_notices.items():
                if not all(notice in entry.get("desc", {}).get(language, "") for notice in notices):
                    fail(f"XR Studio Windows preview requires installation caveats: {language}")

    # Platform feeds are promoted independently after their own approval.
    updater_versions = {"latest.yml": "1.1.4", "latest-mac.yml": "1.0.1"}
    for updater_name, updater_version in updater_versions.items():
        updater_path = ROOT / "ota/xr-studio" / updater_name
        updater_text = updater_path.read_text(encoding="utf-8-sig")
        version_pattern = rf"^version:\s*{re.escape(updater_version)}\s*$"
        if not re.search(version_pattern, updater_text, re.MULTILINE):
            fail(
                f"XR Studio {updater_name} version must be {updater_version}"
            )

    xr_car_tail = (ROOT / "firmware/xr-car-tail/version.yaml").read_text(
        encoding="utf-8"
    )
    required_xr_car_tail_fields = {
        "id": "xr-car-tail",
        "device_type": "XR-CAR-TAIL",
        "version": "2.0.0.8",
        "url": "xr-car-tail-ver-2.0.0.8.bin",
        "image_version": "2.0.0.8",
        "product_code": "24833",
        "image_size": "33516",
        "image_crc32": "693107542",
        "sha256": "7859d406ca265fbd619eba534d7ddcce790b59ffa920c45282ad1ed85d731979",
        "min_bootloader_version": "2.0.0.0",
    }
    for field, expected in required_xr_car_tail_fields.items():
        if not re.search(
            rf"^\s*{re.escape(field)}:\s*['\"]?{re.escape(expected)}['\"]?\s*$",
            xr_car_tail,
            re.MULTILINE,
        ):
            fail(f"XR-CAR-TAIL {field} must be {expected}")
    if not re.search(r"^\s*-\s*24833\s*$", xr_car_tail, re.MULTILINE):
        fail("XR-CAR-TAIL product_codes must contain 24833")

    xr_base = (ROOT / "firmware/xr-base/version.yaml").read_text(
        encoding="utf-8"
    )
    required_xr_base_fields = {
        "id": "xr-base",
        "device_type": "XR-BASE",
        "product_codes": "[24835]",
        "version": "2.1.0.1",
        "url": "app_2.1.0.1.bin",
        "sha256": "2dc53efc696dfce432f8f696724891dfe50d0d9131fe967dde850ee21bf74681",
        "image_version": "2.1.0.1",
        "product_code": "24835",
        "image_size": "30208",
        "image_crc32": "0xDE805C0B",
        "min_bootloader_version": "2.0.0.0",
        "min_studio_version": "1.1.4",
        "source_commit": "cd56ddca80efc0d7acbe3416fd916c75ebfc731a",
        "whole_file_crc32": "0xDE805C0B",
        "whole_file_crc32_scope": "CRC32/ISO-HDLC of unchanged complete APP BIN",
    }
    for field, expected in required_xr_base_fields.items():
        if not re.search(
            rf"^\s*{re.escape(field)}:\s*['\"]?{re.escape(expected)}['\"]?\s*$",
            xr_base,
            re.MULTILINE,
        ):
            fail(f"XR-BASE {field} must be {expected}")

    xr_zero_imu = (ROOT / "firmware/xr-zero-imu/version.yaml").read_text(
        encoding="utf-8"
    )
    required_xr_zero_imu_fields = {
        "id": "xr-zero-imu",
        "device_type": "XR-ZERO-IMU",
        "product_codes": "[24836]",
        "version": "2.1.5.0",
        "url": "app_2.1.5.0.bin",
        "sha256": "f6f550f6a076bd5443de3586f5bb997d89b547c229ed10ae25db36cf35876a46",
        "image_version": "2.1.5.0",
        "product_code": "24836",
        "image_size": "40240",
        "image_crc32": "0x146C43FF",
        "min_bootloader_version": "2.0.0.0",
        "source_commit": "a893691069bed02234d6fa794c1f9a918d7fc8fb",
        "whole_file_crc32": "0x146C43FF",
        "whole_file_crc32_scope": "CRC32/ISO-HDLC of unchanged complete APP BIN",
    }
    for field, expected in required_xr_zero_imu_fields.items():
        if not re.search(
            rf"^\s*{re.escape(field)}:\s*['\"]?{re.escape(expected)}['\"]?\s*$",
            xr_zero_imu,
            re.MULTILINE,
        ):
            fail(f"XR-ZERO-IMU {field} must be {expected}")

    xr_zero_production = (
        ROOT / "firmware/xr-zero-imu/production.yaml"
    ).read_text(encoding="utf-8")
    required_xr_zero_production_fields = {
        "id": "xr-zero-imu",
        "device_type": "XR-ZERO-IMU",
        "product_codes": "[24836]",
        "version": "BL2.0.0.1-APP2.1.5.0",
        "url": "xr-zero-imu-bl2.0.0.1-app2.1.5.0-production.zip",
        "size": "137445",
        "sha256": "06c843027d4e43b33fad1f49db01d9ec41f7536a996f3a90eb810b8dbdd6139d",
        "merged_bin_size": "52528",
        "merged_bin_sha256": "c04cb1c28b731a9ab186791135f7a01a784d82947b5a31da4f57b011abade42c",
        "bin_start_address": "0x08000000",
        "mass_erase_allowed": "false",
        "data_included": "false",
        "option_bytes_included": "false",
        "app_ota": "false",
        "source_commit": "a893691069bed02234d6fa794c1f9a918d7fc8fb",
        "factory_tool_commit": "373eb09",
        "evidence_commit": "3e3d35d",
    }
    for field, expected in required_xr_zero_production_fields.items():
        if not re.search(
            rf"^\s*{re.escape(field)}:\s*['\"]?{re.escape(expected)}['\"]?\s*$",
            xr_zero_production,
            re.MULTILINE,
        ):
            fail(f"XR-ZERO-IMU production {field} must be {expected}")

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
