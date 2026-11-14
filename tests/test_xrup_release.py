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
F030_2S_CATALOG = "firmware/xr-zero-imu/f030/layout3/2s/version.yaml"
F030_3S_CATALOG = "firmware/xr-zero-imu/f030/layout3/3s/version.yaml"


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
        for product in ("mxbit", "xr-base", "xr-car-tail", "xr-aud-01"):
            expected = validate.yaml_urls(
                ROOT / f"firmware/{product}/version.yaml", f"firmware/{product}/"
            )
            self.assertTrue(expected)
            self.assertTrue(expected <= objects)
        self.assertEqual(
            {
                key
                for key in objects
                if key.startswith("firmware/xr-zero-imu/f030/layout3/")
            },
            {
                "firmware/xr-zero-imu/f030/layout3/2s/app_0.1.0.10.bin",
                "firmware/xr-zero-imu/f030/layout3/3s/app_0.1.0.10.bin",
            },
        )
        self.assertFalse(
            any(
                key.startswith("firmware/xr-zero-imu/")
                and "/f030/layout3/" not in key
                for key in objects
            )
        )
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

    def test_f030_catalogs_are_paired_and_strictly_isolated(self):
        two_s = textwrap.dedent("""\
            product:
              id: xr-zero-imu
              device_type: XR-ZERO-IMU
              product_codes: [24836]
            firmware:
              app:
                version: "0.1.0.10"
                image_version: "0.1.0.10"
                url: "app_0.1.0.10.bin"
                product_code: 24836
                target_id: "0xF0304B32"
                layout_version: 3
                app_base: "0x08002000"
                battery_cells: 2
                min_studio_version: "1.1.10"
                min_bootloader_version: "0.1.0.4"
                image_size: 55160
                image_crc32: "0x1B7B9AC9"
                sha256: "24e8218da83baf5de5d464b9593228aa93f360173ff6f3858b56571abf6a27d4"
                release_notes: "F030 layout3 2S online"
                metadata:
                  source_commit: "082f1b0470af13782c9ac9c5c279e236c24f3516"
                  image_crc32_scope: "CRC32/ISO-HDLC over APP bytes excluding header 0x100..0x13f"
                  sha256_scope: "Unchanged complete APP BIN"
                  software_battery_cells: 2
        """)
        three_s = (two_s
            .replace("battery_cells: 2", "battery_cells: 3")
            .replace("image_size: 55160", "image_size: 55192")
            .replace("image_crc32: \"0x1B7B9AC9\"", "image_crc32: \"0xA8D51A92\"")
            .replace(
                "24e8218da83baf5de5d464b9593228aa93f360173ff6f3858b56571abf6a27d4",
                "d7a34ae15efcefc024272228657be1c66d99c71a1b0a1456ebe776e8ee9f0360",
            )
            .replace("software_battery_cells: 2", "software_battery_cells: 3")
            .replace("layout3 2S", "layout3 3S"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            two_path = root / F030_2S_CATALOG
            three_path = root / F030_3S_CATALOG
            two_path.parent.mkdir(parents=True)
            three_path.parent.mkdir(parents=True)
            two_path.write_text(two_s)
            with patch.object(validate, "ROOT", root):
                with self.assertRaisesRegex(ValueError, "must be added together"):
                    validate.validate_xr_zero_imu_f030_catalogs()
                three_path.write_text(three_s)
                validate.validate_xr_zero_imu_f030_catalogs()
                three_path.write_text(three_s.replace("battery_cells: 3", "battery_cells: 2", 1))
                with self.assertRaisesRegex(ValueError, "3S battery_cells must be 3"):
                    validate.validate_xr_zero_imu_f030_catalogs()

    def test_retired_assets_must_be_manifested_and_unreferenced(self):
        key = "firmware/xr-zero-imu/app_2.1.5.0.bin"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "releases/audit"
            audit.mkdir(parents=True)
            (audit / "retired-assets.json").write_text(json.dumps([
                {"tos_key": key, "reason": "public distribution retired"}
            ]))
            with patch.object(validate, "ROOT", root):
                self.assertEqual(validate.validate_retired_assets({key}, set()), {key})
                with self.assertRaisesRegex(ValueError, "invalid retired asset"):
                    validate.validate_retired_assets({key}, {key})

    def test_zero_full_prefix_retirement_workflow_is_absent(self):
        self.assertFalse((ROOT / ".github/workflows/retire-xr-zero-imu.yml").exists())

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
            F030_2S_CATALOG,
            F030_3S_CATALOG,
        ]
        changes = "".join(f"A\t{path}\n" for path in catalogs)
        changes += "M\tdata.json\nA\tfirmware/xr-aud-01/private.key\n"
        changes += "A\tfirmware/xr-aud-01/factory.bin\nA\tfirmware/xr-aud-01/auth.json\n"
        changes += "A\tfirmware/xr-zero-imu/factory.bin\n"
        changes += "A\tfirmware/xr-zero-imu/factory.hex\n"
        changes += "A\tfirmware/xr-zero-imu/f030/layout3/2s/factory.bin\n"
        changes += "A\tfirmware/xr-zero-imu/f030/layout3/3s/private.key\n"
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
            F030_2S_CATALOG,
            F030_3S_CATALOG,
        ):
            for status in ("D", "R100"):
                result, _ = self.run_metadata_plan(f"{status}\t{catalog}\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("deletion/rename is forbidden", result.stderr)


if __name__ == "__main__":
    unittest.main()
