from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from mere_frontier_handoff import cli


def request(backend: str = "claude", mode: str = "chat", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contractVersion": "mere.run/frontier-handoff-request.v1",
        "backend": backend,
        "mode": mode,
        "prompt": "Summarize three options.",
        "outputFormat": "json",
    }
    value.update(changes)
    return value


class FrontierHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.request_file = self.root / "request.json"
        self.output = self.root / "output"

    def write_request(self, value: dict[str, object]) -> None:
        self.request_file.write_text(json.dumps(value))

    def test_plan_records_hash_without_prompt_or_invocation(self) -> None:
        self.write_request(request())
        with mock.patch.object(cli, "invoke") as invoke:
            manifest = cli.plan(self.request_file, self.output, "unit-1")
        invoke.assert_not_called()
        self.assertEqual(manifest["status"], "planned")
        self.assertNotIn("Summarize three options", (self.output / "run.json").read_text())
        self.assertEqual((self.output / "run.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)

    def test_rejects_invalid_modes_and_unknown_fields(self) -> None:
        for invalid in (
            request(mode="agent"),
            request(access="workspace-write"),
            request(extra="not permitted"),
            request(mode="agent", workspace=str(self.root), access="unbounded"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(cli.HandoffError):
                cli.request_from_bytes(json.dumps(invalid).encode())

    def test_rejects_changed_request_before_execution(self) -> None:
        self.write_request(request())
        manifest = cli.plan(self.request_file, self.output, None)
        self.write_request(request(prompt="Different instruction"))
        with self.assertRaisesRegex(cli.HandoffError, "changed after planning"):
            cli.read_planned_request(manifest)

    def test_commands_constrain_chat_and_agent_access(self) -> None:
        temp = self.root / "temp"
        temp.mkdir()
        last = temp / "last.txt"
        chat = cli.command_for_request(request(), "claude", temp, last)
        self.assertIn("--no-session-persistence", chat)
        self.assertEqual(chat[chat.index("--tools") + 1], "")
        self.assertNotIn("--allowedTools", chat)
        agent = request(mode="agent", workspace=str(self.root), access="workspace-write")
        write = cli.command_for_request(agent, "claude", self.root, last)
        self.assertIn("Edit,Write", write[write.index("--tools") + 1])
        self.assertNotIn("Bash", write)
        codex = cli.command_for_request(request("codex"), "codex", temp, last)
        self.assertEqual(codex[codex.index("--sandbox") + 1], "read-only")
        self.assertIn("--ephemeral", codex)
        self.assertEqual(codex[-1], "-")
        write_codex = cli.command_for_request(request("codex", "agent", workspace=str(self.root), access="workspace-write"), "codex", self.root, last)
        self.assertEqual(write_codex[write_codex.index("--sandbox") + 1], "workspace-write")

    def test_claude_run_writes_private_result_and_verifies_digest(self) -> None:
        self.write_request(request())
        manifest = cli.plan(self.request_file, self.output, "unit-2")
        readiness = {"backend": "claude", "installed": True, "authenticated": True, "version": "Claude 1.0"}
        with mock.patch.object(cli, "backend_readiness", return_value=readiness):
            with mock.patch.object(cli, "executable", return_value="/fake/claude"):
                with mock.patch.object(cli, "invoke", return_value='{"result":"{\\"choice\\":\\"A\\"}","is_error":false}') as invoke:
                    finished = cli.run(self.output / "run.json", 10)
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["outputSha256"], cli.resume(self.output / "run.json")["outputSha256"])
        result = json.loads((self.output / "result.json").read_text())
        self.assertEqual(result["output"], {"choice": "A"})
        self.assertEqual(result["receipt"]["requestSha256"], manifest["request"]["sha256"])
        self.assertEqual((self.output / "result.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(invoke.call_args.args[1], "Summarize three options.")
        self.assertFalse((self.output / ".run.lock").exists())

    def test_codex_run_reads_last_message_and_rejects_duplicate(self) -> None:
        self.write_request(request("codex", outputFormat="text"))
        cli.plan(self.request_file, self.output, "unit-3")
        readiness = {"backend": "codex", "installed": True, "authenticated": True, "version": "codex 1.0"}

        def fake_invoke(command: list[str], prompt: str, cwd: pathlib.Path, timeout: int, *, capture_stdout: bool) -> str:
            del prompt, cwd, timeout
            self.assertFalse(capture_stdout)
            pathlib.Path(command[command.index("--output-last-message") + 1]).write_text("Done.")
            return ""

        with mock.patch.object(cli, "backend_readiness", return_value=readiness):
            with mock.patch.object(cli, "executable", return_value="/fake/codex"):
                with mock.patch.object(cli, "invoke", side_effect=fake_invoke):
                    result = cli.run(self.output / "run.json", 10)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(json.loads((self.output / "result.json").read_text())["output"], "Done.")
        with self.assertRaisesRegex(cli.HandoffError, "only a planned"):
            cli.run(self.output / "run.json", 10)

    def test_failure_does_not_claim_success_or_retry_on_resume(self) -> None:
        self.write_request(request())
        cli.plan(self.request_file, self.output, "unit-4")
        readiness = {"backend": "claude", "installed": True, "authenticated": True, "version": "Claude 1.0"}
        with mock.patch.object(cli, "backend_readiness", return_value=readiness):
            with mock.patch.object(cli, "executable", return_value="/fake/claude"):
                with mock.patch.object(cli, "invoke", side_effect=cli.HandoffError("provider failed", 4)):
                    with self.assertRaises(cli.HandoffError):
                        cli.run(self.output / "run.json", 10)
        self.assertEqual(cli.resume(self.output / "run.json")["status"], "failed")
        self.assertFalse((self.output / "result.json").exists())
        self.assertEqual(cli.cleanup(self.output / "run.json")["cleanup"], "recorded")

    def test_interrupted_run_is_not_reissued(self) -> None:
        self.write_request(request())
        manifest = cli.plan(self.request_file, self.output, "unit-5")
        cli.update_manifest(self.output / "run.json", manifest, status="running")
        (self.output / ".run.lock").write_text("99999999")
        self.assertEqual(cli.resume(self.output / "run.json")["status"], "interrupted")
        self.assertFalse((self.output / ".run.lock").exists())

    def test_result_tampering_is_detected(self) -> None:
        self.write_request(request())
        manifest = cli.plan(self.request_file, self.output, "unit-6")
        (self.output / "result.json").write_text('{"output":{"choice":"altered"}}')
        cli.update_manifest(self.output / "run.json", manifest, status="succeeded", outputSha256="0" * 64)
        with self.assertRaisesRegex(cli.HandoffError, "digest differs"):
            cli.resume(self.output / "run.json")


if __name__ == "__main__":
    unittest.main()
