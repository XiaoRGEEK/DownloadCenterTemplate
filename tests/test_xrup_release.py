"""Control-plane regressions; synthetic fixtures never validate device firmware."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from scripts import prepare_release as prepare
from scripts import validate_release as validate


ROOT = Path(__file__).resolve().parents[1]
CATALOG = "firmware/xr-aud-01/version.yaml"


class XrupReleaseTests(unittest.TestCase):
    def test_prepare_suffixes_and_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".XRUP", ".xrup", ".bin", ".apk"):
                source = Path(directory) / ("fixture" + suffix)
                source.write_bytes(b"synthetic-not-firmware")
                key = "firmware/xr-aud-01/" + source.name
                self.assertEqual(prepare.parse_asset(f"{source}={key}")[1], key)
                with self.assertRaises(prepare.ReleaseError):
                    prepare.parse_asset(f"{source}=firmware/../{source.name}")
            source = Path(directory) / "secret.key"
            source.write_bytes(b"synthetic-not-a-key")
            with self.assertRaises(prepare.ReleaseError):
                prepare.parse_asset(f"{source}=firmware/xr-aud-01/{source.name}")

    def test_manifest_schema_stays_one_and_fields_remain_strict(self):
        fixture = json.loads((ROOT / "tests/fixtures/xrup-release.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "releases").mkdir()
            target = root / "releases/test-xrup-v1.json"
            with patch.object(validate, "ROOT", root):
                target.write_text(json.dumps(fixture))
                self.assertEqual(validate.validate_release_manifests(),
                                 (1, {"firmware/xr-aud-01/fixture.XRUP"}))
                fixture["schema_version"] = 2
                target.write_text(json.dumps(fixture))
                with self.assertRaises(ValueError):
                    validate.validate_release_manifests()
                fixture["schema_version"] = 1
                fixture["assets"][0]["security_profile"] = "not-a-manifest-field"
                target.write_text(json.dumps(fixture))
                with self.assertRaises(ValueError):
                    validate.validate_release_manifests()

    def test_xrup_cannot_be_committed_as_source(self):
        with patch.object(validate, "tracked_files", return_value=["fixture.XRUP"]):
            with self.assertRaisesRegex(ValueError, "binaries are tracked"):
                validate.validate()

    def test_reference_enumeration_preserves_existing_products(self):
        objects, _ = validate.referenced_objects()
        for product in ("mxbit", "xr-base", "xr-car-tail", "xr-aud-01", "xr-zero-imu"):
            expected = validate.yaml_urls(
                ROOT / f"firmware/{product}/version.yaml", f"firmware/{product}/"
            )
            self.assertTrue(expected)
            self.assertTrue(expected <= objects)
        production = validate.yaml_urls(
            ROOT / "firmware/xr-zero-imu/production.yaml", "firmware/xr-zero-imu/"
        )
        self.assertEqual(production, {
            "firmware/xr-zero-imu/"
            "xr-zero-imu-bl2.0.0.1-app2.1.5.0-production.zip"
        })
        self.assertTrue(production <= objects)
        self.assertTrue(any(key.endswith(".XRUP") for key in objects))

    def test_xr_base_catalog_is_app_only_and_version_pinned(self):
        target = ROOT / "firmware/xr-base/version.yaml"
        catalog = target.read_text()
        self.assertIn('url: "app_2.1.0.1.bin"', catalog)
        self.assertIn('min_studio_version: "1.1.4"', catalog)
        for forbidden in (
            'url: "bl',
            'url: "full',
            "production.zip",
            "authorization",
        ):
            self.assertNotIn(forbidden, catalog.lower())

        original = Path.read_text

        def read_text(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            if path == target:
                return text.replace(
                    'min_studio_version: "1.1.4"',
                    'min_studio_version: "1.1.3"',
                )
            return text

        with patch.object(Path, "read_text", read_text):
            with self.assertRaisesRegex(ValueError, "XR-BASE min_studio_version"):
                validate.validate()

    def run_metadata_plan(self, changes):
        # Execute the actual workflow allowlist, not a duplicated approximation.
        workflow = (ROOT / ".github/workflows/deploy-tos.yml").read_text()
        section = workflow.split("      - name: Build strict incremental metadata plan", 1)[1]
        start = section.index('          : > "${RUNNER_TEMP}/deploy-assets.txt"')
        end = section.index("          count=$(", start)
        script = "set -euo pipefail\n" + textwrap.dedent(section[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "changes.tsv").write_text(changes)
            result = subprocess.run(["bash", "-c", script], text=True,
                                    capture_output=True,
                                    env={**os.environ, "RUNNER_TEMP": directory})
            plans = {name: (root / f"deploy-{name}.txt").read_text().splitlines()
                     for name in ("assets", "entrypoints", "final")}
            return result, plans

    def test_catalog_deploys_as_entrypoint_and_private_files_are_excluded(self):
        catalogs = [
            CATALOG,
            "firmware/mxbit/version.yaml",
            "firmware/xr-base/version.yaml",
            "firmware/xr-car-tail/version.yaml",
            "firmware/xr-zero-imu/version.yaml",
            "firmware/xr-zero-imu/production.yaml",
        ]
        changes = "".join(f"A\t{path}\n" for path in catalogs)
        changes += "M\tdata.json\nA\tfirmware/xr-aud-01/private.key\n"
        changes += "A\tfirmware/xr-aud-01/factory.bin\nA\tfirmware/xr-aud-01/auth.json\n"
        changes += "A\tfirmware/xr-zero-imu/factory.bin\n"
        changes += "A\tfirmware/xr-zero-imu/factory.hex\n"
        changes += "A\tfirmware/xr-base/full.bin\n"
        changes += "A\tfirmware/xr-base/authorization.json\n"
        result, plans = self.run_metadata_plan(changes)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(plans, {"assets": [], "entrypoints": catalogs, "final": ["data.json"]})

    def test_catalog_deletion_and_rename_remain_forbidden(self):
        for catalog in (
            CATALOG,
            "firmware/xr-base/version.yaml",
            "firmware/xr-zero-imu/production.yaml",
        ):
            for status in ("D", "R100"):
                result, _ = self.run_metadata_plan(f"{status}\t{catalog}\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("deletion/rename is forbidden", result.stderr)


if __name__ == "__main__":
    unittest.main()
