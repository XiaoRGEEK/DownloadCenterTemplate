"""XR Block website releases must preserve the reviewed Windows contract."""

import copy
import unittest
from unittest.mock import patch

from scripts import validate_release as validate


class XrBlockReleaseTests(unittest.TestCase):
    def setUp(self):
        self.objects, self.data = validate.referenced_objects()

    def entry(self, data=None):
        return next(
            item
            for item in (self.data if data is None else data)
            if item.get("name", {}).get("en") == "XRBlock Scratch3.0 Software"
        )

    def validate_data(self, data):
        with patch.object(
            validate, "referenced_objects", return_value=(self.objects, data)
        ):
            return validate.validate()

    def test_website_release_is_pinned_to_windows_x64_3_0_0(self):
        entry = self.entry()
        self.assertEqual(entry["version"], "v3.0.0")
        self.assertEqual(
            entry["link"], ["software/pc/XR Block_3.0.0_x64-setup.exe"]
        )
        self.assertEqual(entry["oldVersion"], ["software/pc/XR Block v2.3.3.exe"])
        validate.validate()

    def test_wrong_version_link_or_rollback_is_rejected(self):
        for field, value in (
            ("version", "v2.3.3"),
            ("link", ["software/pc/XR Block v2.3.3.exe"]),
            ("oldVersion", ["software/pc/XR Block v2.2.6.exe"]),
        ):
            with self.subTest(field=field):
                data = copy.deepcopy(self.data)
                self.entry(data)[field] = value
                with self.assertRaisesRegex(ValueError, "Windows x64 v3.0.0"):
                    self.validate_data(data)

    def test_unsigned_installer_notice_is_required(self):
        for language, notice in {
            "en": "not Authenticode signed",
            "zh": "未做 Authenticode 数字签名",
        }.items():
            with self.subTest(language=language):
                data = copy.deepcopy(self.data)
                desc = self.entry(data)["desc"]
                self.assertIn(notice, desc[language])
                desc[language] = desc[language].replace(notice, "")
                with self.assertRaisesRegex(ValueError, "unsigned installer notice"):
                    self.validate_data(data)


if __name__ == "__main__":
    unittest.main()
