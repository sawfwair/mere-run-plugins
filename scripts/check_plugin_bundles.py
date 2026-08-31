"""Contract regression checks; synthetic manifests are never signed releases."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


class BundleContractTests(unittest.TestCase):
    def test_distribution_recipes_match_their_packages(self) -> None:
        expected = {
            "animatic-tools",
            "face-tools",
            "film-tools",
            "geo-tools",
            "image-tools",
            "perform",
            "vfx-tools",
            "workflow-tools",
        }
        pillow_bundles = {"animatic-tools", "face-tools", "geo-tools", "image-tools", "vfx-tools"}
        recipes = {path.parent.name: path for path in ROOT.glob("bundles/*/recipe.json")}
        self.assertEqual(set(recipes), expected)
        for bundle, path in sorted(recipes.items()):
            recipe = json.loads(path.read_text())
            package_path = ROOT / recipe.get("packagePath", f"packages/{recipe['package']}")
            project = (package_path / "pyproject.toml").read_text()
            name = re.search(r'^name = "([^"]+)"$', project, re.MULTILINE)
            self.assertIsNotNone(name, bundle)
            self.assertEqual(name.group(1), recipe["package"], bundle)
            self.assertRegex(recipe["appBundle"], r"^[A-Za-z0-9]+\.app$")
            self.assertRegex(recipe.get("appExecutable", recipe["appBundle"][:-4]), r"^[A-Za-z0-9]+$")
            self.assertEqual(recipe.get("bundleIdentifier", f"run.mere.plugins.{recipe['package']}"),
                             f"run.mere.plugins.{recipe['package']}")
            self.assertRegex(recipe["python"]["sha256"], r"^[0-9a-f]{64}$")
            for support in recipe.get("supportPackages", []):
                support_path = ROOT / support["packagePath"]
                self.assertTrue(support_path.is_dir(), f"{bundle}: {support['packagePath']}")
                support_project = (support_path / "pyproject.toml").read_text()
                support_name = re.search(r'^name = "([^"]+)"$', support_project, re.MULTILINE)
                self.assertIsNotNone(support_name, bundle)
                self.assertEqual(support_name.group(1), support["package"], bundle)
            self.assertTrue(recipe["entrypoints"])
            module_roots = set()
            for executable, module in recipe["entrypoints"].items():
                self.assertRegex(executable, r"^mere-[a-z0-9-]+$")
                self.assertRegex(module, r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
                module_roots.add(module.split(".", 1)[0])
            if bundle != "workflow-tools":
                inputs = path.parent
                for required in ("BUNDLE_NOTICES.txt", "build-constraints.txt", "builder-requirements.in",
                                 "builder-requirements.lock", "frozen_entrypoint.py", "launcher.c",
                                 "requirements.lock"):
                    self.assertTrue((inputs / required).is_file(), f"{bundle}: {required}")
                self.assertTrue(module_roots.issubset(set(recipe.get("collectAll", []))), bundle)
                self.assertIn(recipe["package"], recipe.get("copyMetadata", []), bundle)
                self.assertIn("pyinstaller", recipe.get("copyMetadata", []), bundle)
                frozen = (inputs / "frozen_entrypoint.py").read_text()
                for module in recipe["entrypoints"].values():
                    self.assertIn(f'"{module}"', frozen, bundle)
                requirements = (inputs / "requirements.lock").read_text().lower()
                if bundle in pillow_bundles:
                    self.assertIn("pillow==12.3.0 \\", requirements, bundle)
                    self.assertIn("PIL", recipe.get("collectAll", []), bundle)
                    self.assertIn("pillow", recipe.get("copyMetadata", []), bundle)
                else:
                    self.assertNotIn("pillow==", requirements, bundle)
                    self.assertNotIn("PIL", recipe.get("collectAll", []), bundle)
                    self.assertNotIn("pillow", recipe.get("copyMetadata", []), bundle)

                if bundle == "geo-tools":
                    builder_requirements = (inputs / "builder-requirements.lock").read_text().lower()
                    self.assertIn("setuptools==84.0.0 \\", builder_requirements)
                    self.assertIn("wheel==0.48.0 \\", builder_requirements)
                    source_builds = recipe.get("sourceBuilds", [])
                    self.assertEqual(
                        source_builds,
                        [
                            {
                                "name": "asciitree",
                                "version": "0.3.3",
                                "url": "https://files.pythonhosted.org/packages/2d/6a/885bc91484e1aa8f618f6f0228d76d0e67000b0fdd6090673b777e311913/asciitree-0.3.3.tar.gz",
                                "sha256": "4aa4b9b649f85e3fcb343363d97564aa1fb62e249677f2e18a96765145cc0f6e",
                                "license": "MIT",
                                "licenseFile": "LICENSE",
                            }
                        ],
                    )
                    self.assertNotIn("asciitree==", requirements)
                    for requirement in (
                        "numcodecs==0.15.1 \\",
                        "numpy==2.5.2 \\",
                        "pillow==12.3.0 \\",
                        "planetary-computer==1.0.0 \\",
                        "pystac-client==0.9.0 \\",
                        "rasterio==1.5.1 \\",
                        "safetensors==0.8.0 \\",
                        "zarr==2.18.0 \\",
                    ):
                        self.assertIn(requirement, requirements, bundle)

    def test_native_notices_match_the_pinned_anydoc_dependency(self) -> None:
        inputs = ROOT / "bundles/workflow-tools"
        inventory = json.loads((inputs / "anydoc-native-inventory.json").read_text())
        notices = (inputs / "anydoc-native-notices.txt").read_bytes()
        self.assertIn(f"firecrawl-anydoc=={inventory['version']} ", (inputs / "requirements.lock").read_text())
        self.assertEqual(hashlib.sha256(notices).hexdigest(), inventory["noticesSHA256"])
        self.assertTrue(inventory["packages"])
        for package in inventory["packages"]:
            self.assertTrue(package["licenseFiles"], package["name"])
            for license_file in package["licenseFiles"]:
                self.assertIn(license_file["sha256"].encode(), notices, package["name"])

    def test_manifest_example_and_rejected_boundaries(self) -> None:
        schema = json.loads((ROOT / "contracts/plugin-bundle.v1.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        example = json.loads((ROOT / "examples/plugin-bundles/document-tools.manifest.json").read_text())
        self.assertTrue(validator.is_valid(example))
        for field, value in [("package", "../escape"), ("appBundle", "../escape.app"),
                             ("sequence", 0), ("platform", "linux-x86_64"), ("expiresAt", "invalid")]:
            invalid = dict(example)
            invalid[field] = value
            self.assertFalse(validator.is_valid(invalid), field)
        for field, value in [("url", "http://example.com/bundle.dmg"), ("size", -1),
                             ("size", 1073741825), ("sha256", "not-a-hash")]:
            invalid = copy.deepcopy(example)
            invalid["artifact"][field] = value
            self.assertFalse(validator.is_valid(invalid), field)

    def test_catalog_keeps_source_compatibility_and_rejects_untrusted_keys(self) -> None:
        schema = json.loads((ROOT / "contracts/catalog.v1.schema.json").read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        catalog = json.loads((ROOT / "catalog/plugins.v1.json").read_text())
        self.assertTrue(validator.is_valid(catalog))
        channel = next(iter(catalog["plugins"][0]["channels"].values()))
        channel["bundles"] = {"macos-arm64": "https://example.com/release.json"}
        self.assertTrue(validator.is_valid(catalog))
        channel["publicKey"] = "catalogs cannot grant trust"
        self.assertFalse(validator.is_valid(catalog))

    def test_envelope_cannot_supply_a_public_key(self) -> None:
        schema = json.loads((ROOT / "contracts/plugin-bundle-envelope.v1.schema.json").read_text())
        validator = Draft202012Validator(schema)
        envelope = {"contractVersion": "mere.run/plugin-bundle-envelope.v1", "keyID": "mere-release-1",
                    "payload": "e30=", "signature": "A" * 86 + "=="}
        self.assertTrue(validator.is_valid(envelope))
        envelope["publicKey"] = "untrusted"
        self.assertFalse(validator.is_valid(envelope))


if __name__ == "__main__":
    unittest.main()
