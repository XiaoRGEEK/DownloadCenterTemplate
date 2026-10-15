"""Website previews must preserve rollbacks, caveats and stable feeds."""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from unittest.mock import patch

from scripts import validate_release as validate


ROOT = Path(__file__).resolve().parents[1]


class StudioPreviewTests(unittest.TestCase):
    def setUp(self):
        self.objects, self.data = validate.referenced_objects()

    def entry(self, platform, data=None):
        return next(item for item in (self.data if data is None else data)
                    if item.get("name", {}).get("en") == "XR Studio"
                    and item["platform"] == platform)

    def validate_data(self, data):
        with patch.object(validate, "referenced_objects", return_value=(self.objects, data)):
            return validate.validate()

    def test_preview_website_versions_are_valid(self):
        self.assertEqual(self.entry("mac")["version"], "v1.1.3")
        self.assertEqual(self.entry("windows")["version"], "v1.1.4")
        for platform in ("mac", "windows"):
            self.assertEqual(self.entry(platform)["platformVersions"],
                             {"windows": "v1.1.4", "mac": "v1.1.3"})
        validate.validate()

    def test_wrong_windows_version_or_stale_cross_platform_label_is_rejected(self):
        for field, value in (("version", "v1.0.1"), ("link", ["unpublished.exe"]),
                             ("platformVersions", {"windows": "v1.0.1", "mac": "v1.1.3"})):
            data = copy.deepcopy(self.data)
            self.entry("windows", data)[field] = value
            with self.assertRaisesRegex(ValueError, "invalid XR Studio"):
                self.validate_data(data)

    def test_windows_rollback_and_installation_caveats_are_required(self):
        data = copy.deepcopy(self.data)
        self.entry("windows", data)["oldVersion"] = []
        with self.assertRaisesRegex(ValueError, "Windows preview requires.*rollback"):
            self.validate_data(data)
        notices = {
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
        for language, phrases in notices.items():
            for phrase in phrases:
                with self.subTest(language=language, phrase=phrase):
                    data = copy.deepcopy(self.data)
                    desc = self.entry("windows", data)["desc"]
                    self.assertIn(phrase, desc[language])
                    desc[language] = desc[language].replace(phrase, "")
                    with self.assertRaisesRegex(ValueError, "installation caveats"):
                        self.validate_data(data)

    def test_bilingual_preview_and_rollback_are_required(self):
        for field, value in (("oldVersion", []), ("desc", {"en": "Preview", "zh": "正式版"}),
                             ("desc", {"en": "Stable", "zh": "客户试用"})):
            data = copy.deepcopy(self.data)
            self.entry("mac", data)[field] = value
            with self.assertRaisesRegex(ValueError, "preview requires"):
                self.validate_data(data)

    def test_stable_feeds_are_byte_identical_to_approved_versions(self):
        # Each platform promotion is separately reviewed and updates this contract.
        expected = {
            "latest.yml": "535cd6b3641f4416f9a75fbc90ba0b519185034601b2ef1ffb888bd84ef7994b",
            "latest-mac.yml": "ebb0304a80e3ad0ef31d587a548ef7eb9195d42cf37afdc853c9a4ade932cede",
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / "ota/xr-studio" / name).read_bytes()).hexdigest(), digest)

    def test_validator_rejects_unreviewed_feed_promotion(self):
        original = Path.read_text
        cases = (
            ("latest.yml", "version: 1.1.4", "version: 1.1.5", "version must be 1.1.4"),
            ("latest-mac.yml", "version: 1.0.1", "version: 1.1.4", "version must be 1.0.1"),
        )
        for name, approved, unreviewed, error in cases:
            target = ROOT / "ota/xr-studio" / name
            def read_text(path, *args, **kwargs):
                text = original(path, *args, **kwargs)
                return text.replace(approved, unreviewed) if path == target else text
            with patch.object(Path, "read_text", read_text):
                with self.assertRaisesRegex(ValueError, error):
                    validate.validate()

    def test_preview_manifest_contains_only_website_dmg(self):
        manifest = json.loads((ROOT / "releases/xr-studio-v1.1.3-preview.json").read_text())
        self.assertEqual(manifest["assets"][0], {
            "name": "xr-studio-1.1.3-mac-arm64.dmg",
            "tos_key": "software/pc/xr-studio-1.1.3-mac-arm64.dmg",
            "size": 127937786,
            "sha256": "d5e6b1e8cd8af2f2ca727a2015e52d5df59308b2d0e8f2733924d7f2bd036d90",
        })
        self.assertFalse(any(key.startswith("ota/xr-studio/") and "1.1.3" in key
                             for key in self.objects))

    def test_windows_preview_manifest_contains_only_website_exe_and_zip(self):
        manifest = json.loads((ROOT / "releases/xr-studio-win-v1.1.4-preview.json").read_text())
        self.assertEqual(manifest["assets"], [
            {"name": "xr-studio-1.1.4-win-x64.exe",
             "tos_key": "software/pc/xr-studio-1.1.4-win-x64.exe",
             "size": 111991953,
             "sha256": "0655f0d9d838ebc801c217a9200ef67c266fc40b36b9dc4af3f75f954c89ab7a"},
            {"name": "xr-studio-1.1.4-win-x64.zip",
             "tos_key": "software/pc/xr-studio-1.1.4-win-x64.zip",
             "size": 152683425,
             "sha256": "46b1a77c1a177e7491764a000ca3584bfcff1c5395e5885820d502392d9d273e"},
        ])

    def test_actual_workflow_public_link_check_accepts_only_preview_release(self):
        workflow = (ROOT / ".github/workflows/deploy-tos.yml").read_text()
        expression = re.search(r"jq -e '([^']+)' \"\$\{public_data\}\"", workflow).group(1)
        result = subprocess.run(["jq", "-e", expression], input=json.dumps(self.data),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for platform in ("mac", "windows"):
            data = copy.deepcopy(self.data)
            self.entry(platform, data)["link"] = self.entry(platform, data)["oldVersion"]
            result = subprocess.run(["jq", "-e", expression], input=json.dumps(data),
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
