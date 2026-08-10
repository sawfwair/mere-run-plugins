from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from mere_workflow_tools import identity_cli


class IdentityCliTests(unittest.TestCase):
    def test_public_contract_is_product_neutral(self) -> None:
        manifest = identity_cli.plugin_manifest()
        catalog = identity_cli.graph_catalog()

        self.assertEqual(manifest["name"], "mere-identity-tools")
        self.assertEqual(catalog["provider_id"], "mere-identity-tools")
        self.assertEqual(
            sorted(node["kind"] for node in catalog["nodes"]),
            identity_cli.NODE_KINDS,
        )
        serialized = json.dumps({"manifest": manifest, "catalog": catalog}).lower()
        self.assertIn("identity", serialized)
        self.assertNotIn("product-specific", serialized)

    def test_doctor_fails_closed_without_a_backend(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.dict(os.environ, {identity_cli.BACKEND_ENV: "missing-identity-backend"}),
            mock.patch("mere_workflow_tools.identity_cli.shutil.which", return_value=None),
            redirect_stdout(output),
        ):
            status = identity_cli.doctor()

        self.assertEqual(status, 3)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_backend_arguments_are_forwarded_without_a_shell(self) -> None:
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.dict(os.environ, {identity_cli.BACKEND_ENV: "/tmp/backend --mode local"}),
            mock.patch("mere_workflow_tools.identity_cli.pathlib.Path.is_file", return_value=True),
            mock.patch("mere_workflow_tools.identity_cli.subprocess.run", return_value=completed) as run,
        ):
            status = identity_cli.run_backend(["doctor", "--json"])

        self.assertEqual(status, 0)
        run.assert_called_once_with(
            ["/tmp/backend", "--mode", "local", "doctor", "--json"],
            check=False,
        )

    def test_graph_catalog_fails_closed_through_the_configured_backend(self) -> None:
        with (
            mock.patch("sys.argv", ["mere-identity-tools", "graph", "catalog", "--json"]),
            mock.patch("mere_workflow_tools.identity_cli.run_backend", return_value=7) as run,
        ):
            self.assertEqual(identity_cli.main(), 7)

        run.assert_called_once_with(["graph", "catalog", "--json"])

    def test_stage_uses_neutral_registry_flag_and_forwards_backend_contract(self) -> None:
        with (
            mock.patch(
                "sys.argv",
                [
                    "mere-identity-tools",
                    "stage",
                    "./source.jsonl",
                    "--pairing-code",
                    "pairing_123",
                    "--registry-url",
                    "https://identity.example",
                    "--device-id",
                    "device_123",
                    "--json",
                ],
            ),
            mock.patch("mere_workflow_tools.identity_cli.run_backend", return_value=0) as run,
        ):
            self.assertEqual(identity_cli.main(), 0)

        run.assert_called_once_with(
            [
                "stage",
                "./source.jsonl",
                "--pairing-code",
                "pairing_123",
                "--api-url",
                "https://identity.example",
                "--device-id",
                "device_123",
                "--json",
            ]
        )


if __name__ == "__main__":
    unittest.main()
