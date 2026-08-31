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
        expected = {"animatic-tools", "face-tools", "image-tools", "workflow-tools"}
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
            self.assertTrue(recipe["entrypoints"])
            for executable, module in recipe["entrypoints"].items():
                self.assertRegex(executable, r"^mere-[a-z0-9-]+$")
                self.assertRegex(module, r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
            if bundle != "workflow-tools":
                inputs = path.parent
                self.assertIn("pillow==12.3.0 \\", (inputs / "requirements.lock").read_text())
                for required in ("BUNDLE_NOTICES.txt", "build-constraints.txt", "builder-requirements.lock",
                                 "frozen_entrypoint.py", "launcher.c", "requirements.lock"):
                    self.assertTrue((inputs / required).is_file(), f"{bundle}: {required}")

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
