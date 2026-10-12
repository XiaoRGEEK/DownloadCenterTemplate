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
        self.assertEqual(self.entry("mac")["version"], "v1.1.2")
        self.assertEqual(self.entry("windows")["version"], "v1.1.2")
        for platform in ("mac", "windows"):
            self.assertEqual(self.entry(platform)["platformVersions"],
                             {"windows": "v1.1.2", "mac": "v1.1.2"})
        validate.validate()

    def test_wrong_windows_version_or_stale_cross_platform_label_is_rejected(self):
        for field, value in (("version", "v1.0.1"), ("link", ["unpublished.exe"]),
                             ("platformVersions", {"windows": "v1.0.1", "mac": "v1.0.1"})):
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
            "en": ("Preview", "not Authenticode signed", "All users", "26200",
                   "/S /currentuser", "System.dll", "0xc0000005", "unresolved",
                   "per-user installation is not validated", "ZIP", "await user confirmation"),
            "zh": ("客户试用", "未做 Authenticode 签名", "所有用户", "26200",
                   "/S /currentuser", "System.dll", "0xc0000005", "根因未定位",
                   "按用户安装尚未通过验收", "ZIP", "待用户确认"),
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

    def test_stable_feeds_are_byte_identical_to_approved_1_0_1(self):
        # Promotion is a separate reviewed release that must update this contract.
        expected = {
            "latest.yml": "85a9dc43fe631139a2ce1c7fa6040349be6a7d1e27a8e03063691865a4e0438a",
            "latest-mac.yml": "ebb0304a80e3ad0ef31d587a548ef7eb9195d42cf37afdc853c9a4ade932cede",
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / "ota/xr-studio" / name).read_bytes()).hexdigest(), digest)

    def test_validator_rejects_stable_feed_promotion(self):
        original = Path.read_text
        for name in ("latest.yml", "latest-mac.yml"):
            target = ROOT / "ota/xr-studio" / name
            def read_text(path, *args, **kwargs):
                text = original(path, *args, **kwargs)
                return text.replace("version: 1.0.1", "version: 1.1.2") if path == target else text
            with patch.object(Path, "read_text", read_text):
                with self.assertRaisesRegex(ValueError, "version must be 1.0.1"):
                    validate.validate()

    def test_preview_manifest_contains_only_website_dmg(self):
        manifest = json.loads((ROOT / "releases/xr-studio-mac-v1.1.2-preview.json").read_text())
        self.assertEqual(len(manifest["assets"]), 1)
        self.assertEqual(manifest["assets"][0], {
            "name": "xr-studio-1.1.2-mac-arm64.dmg",
            "tos_key": "software/pc/xr-studio-1.1.2-mac-arm64.dmg",
            "size": 127910769,
            "sha256": "a8b9b556c8e61d1aa26c665746428461466d21d22be65167412d5e8ae1ce3a51",
        })
        self.assertFalse(any(key.startswith("ota/xr-studio/") and "1.1.2" in key
                             for key in self.objects))

    def test_windows_preview_manifest_contains_only_website_exe_and_zip(self):
        manifest = json.loads((ROOT / "releases/xr-studio-win-v1.1.2-preview.json").read_text())
        self.assertEqual(manifest["assets"], [
            {"name": "xr-studio-1.1.2-win-x64.exe",
             "tos_key": "software/pc/xr-studio-1.1.2-win-x64.exe",
             "size": 111652095,
             "sha256": "36ec7b8d83929f58ff7d1410305843e5658e49b5c16f004d01b85067f96cfce9"},
            {"name": "xr-studio-1.1.2-win-x64.zip",
             "tos_key": "software/pc/xr-studio-1.1.2-win-x64.zip",
             "size": 152207363,
             "sha256": "b7d84517fd4ac421a13e4abcb411ddecb35b1642fd1ca3fff1c80abedf3fdeff"},
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
