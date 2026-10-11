"""Website preview must not promote stable feeds or the Windows download."""

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

    def test_mixed_platform_website_is_valid(self):
        self.assertEqual(self.entry("mac")["version"], "v1.1.2")
        self.assertEqual(self.entry("windows")["version"], "v1.0.1")
        for platform in ("mac", "windows"):
            self.assertEqual(self.entry(platform)["platformVersions"],
                             {"windows": "v1.0.1", "mac": "v1.1.2"})
        validate.validate()

    def test_windows_promotion_or_stale_cross_platform_label_is_rejected(self):
        for field, value in (("version", "v1.1.2"), ("link", ["unpublished.exe"]),
                             ("platformVersions", {"windows": "v1.0.1", "mac": "v1.0.1"})):
            data = copy.deepcopy(self.data)
            self.entry("windows", data)[field] = value
            with self.assertRaisesRegex(ValueError, "invalid XR Studio"):
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

    def test_actual_workflow_public_link_check_accepts_only_mixed_release(self):
        workflow = (ROOT / ".github/workflows/deploy-tos.yml").read_text()
        expression = re.search(r"jq -e '([^']+)' \"\$\{public_data\}\"", workflow).group(1)
        result = subprocess.run(["jq", "-e", expression], input=json.dumps(self.data),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = copy.deepcopy(self.data)
        self.entry("mac", data)["link"] = self.entry("mac", data)["oldVersion"]
        result = subprocess.run(["jq", "-e", expression], input=json.dumps(data),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
