"""Check scoring boundaries and participant isolation before model runs."""

import tempfile
import unittest
from pathlib import Path

from benchmark import ROOT, file_hashes, mapping, prepare, read_json, result_template, score, validate


def completed(status: str) -> dict[str, object]:
    result = result_template()
    for stage in ("stage1", "stage2"):
        for key, record in mapping(result[stage]).items():
            if isinstance(record, dict):
                record.update(status=status, observation="Observed in browser", evidence="capture.png")
                if key == "C05" and status == "fail":
                    record["failureCause"] = "site-behavior"
    return result


class BenchmarkTests(unittest.TestCase):
    def test_pack_validates(self) -> None:
        self.assertEqual(validate()["stableCases"], 24)

    def test_pending_is_not_a_score(self) -> None:
        result = score(result_template())
        self.assertIsNone(mapping(result["initialFunctionality"])["percent"])
        self.assertIsNone(mapping(result["regression"])["percent"])

    def test_zero_baseline_passes_has_no_regression_percentage(self) -> None:
        result = score(completed("fail"))
        self.assertEqual(mapping(result["initialFunctionality"])["percent"], 0)
        self.assertIsNone(mapping(result["regression"])["percent"])

    def test_intentional_rule_changes_are_not_regressions(self) -> None:
        result = completed("pass")
        after = mapping(result["stage2"])
        after["C01"] = {"status": "fail", "observation": "Allowed adjacency", "evidence": "c01.png"}
        result["stage2"] = after
        scored = score(result)
        self.assertEqual(mapping(scored["regression"])["percent"], 0)
        self.assertEqual(mapping(scored["changedRuleSuccess"])["percent"], 83.33)

    def test_regression_uses_previously_passing_stable_cases(self) -> None:
        result = completed("pass")
        before = mapping(result["stage1"])
        before["F01"] = {"status": "fail", "observation": "Missing room", "evidence": "f01.png"}
        result["stage1"] = before
        after = mapping(result["stage2"])
        after["F02"] = {"status": "fail", "observation": "Wrong filter", "evidence": "f02.png"}
        result["stage2"] = after
        regression = mapping(score(result)["regression"])
        self.assertEqual(regression["previouslyPassingStableCases"], 23)
        self.assertEqual(regression["brokenCases"], ["F02"])
        self.assertEqual(regression["percent"], 4.35)

    def test_pending_eligible_case_keeps_regression_pending(self) -> None:
        result = completed("pass")
        after = mapping(result["stage2"])
        after["F01"] = {"status": "pending"}
        result["stage2"] = after
        self.assertIsNone(mapping(score(result)["regression"])["percent"])

    def test_missing_or_extra_case_is_rejected(self) -> None:
        for key in ("F01", "EXTRA"):
            result = completed("pass")
            before = mapping(result["stage1"])
            if key == "F01":
                del before[key]
            else:
                before[key] = {"status": "pass"}
            result["stage1"] = before
            with self.assertRaises(ValueError):
                score(result)

    def test_final_observation_requires_evidence(self) -> None:
        result = completed("pass")
        before = mapping(result["stage1"])
        before["F01"] = {"status": "pass", "observation": "Looks right", "evidence": None}
        result["stage1"] = before
        with self.assertRaises(ValueError):
            score(result)

    def test_date_checks_contribute_to_functionality_and_regression(self) -> None:
        result = completed("pass")
        after = mapping(result["stage2"])
        for key in ("F23", "F24"):
            after[key] = {"status": "fail", "observation": "Booking date shifted", "evidence": "dates.png"}
        result["stage2"] = after
        scored = score(result)
        self.assertEqual(mapping(scored["initialFunctionality"])["total"], 26)
        self.assertEqual(mapping(scored["updatedFunctionality"])["percent"], 91.67)
        self.assertEqual(mapping(scored["regression"])["brokenCases"], ["F23", "F24"])

    def test_migration_prerequisite_is_distinct_from_observed_failure(self) -> None:
        for cause in ("stage1-prerequisite", "site-behavior"):
            result = completed("pass")
            after = mapping(result["stage2"])
            after["C05"] = {
                "status": "fail", "observation": "Recorded failed step", "evidence": "migration.json",
                "failureCause": cause,
            }
            result["stage2"] = after
            scored = score(result)
            self.assertEqual(mapping(scored["migration"])["failureCause"], cause)
            self.assertEqual(mapping(scored["changedRuleSuccess"])["percent"], 83.33)

    def test_migration_failure_requires_an_explicit_cause(self) -> None:
        result = completed("pass")
        after = mapping(result["stage2"])
        after["C05"] = {"status": "fail", "observation": "Cannot create fixture", "evidence": "setup.png"}
        result["stage2"] = after
        with self.assertRaises(ValueError):
            score(result)

    def test_passing_migration_cannot_claim_a_prerequisite_failure(self) -> None:
        result = completed("pass")
        after = mapping(result["stage2"])
        after["C05"] = {
            "status": "pass", "observation": "No migration observed", "evidence": "setup.png",
            "failureCause": "stage1-prerequisite",
        }
        result["stage2"] = after
        with self.assertRaises(ValueError):
            score(result)

    def test_prepare_preserves_existing_and_isolates_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "campaign"
            prepare(output)
            manifest = mapping(read_json(output / "operator/manifest.json"))
            self.assertEqual(manifest["status"], "prepared-not-run")
            self.assertEqual((output / "operator/benchmark.py").read_bytes(), (ROOT / "benchmark.py").read_bytes())
            a = output / "entries/A"
            b = output / "entries/B"
            self.assertEqual(file_hashes(a), file_hashes(b))
            self.assertFalse((a / "FOLLOW_UP.md").exists())
            self.assertFalse((a / "checks.json").exists())
            self.assertFalse((a / "RUN_SETUP.md").exists())
            self.assertEqual(
                (output / "operator/RUN_SETUP.md").read_bytes(), (ROOT / "RUN_SETUP.md").read_bytes(),
            )
            (a / "site/app.js").write_text("// Participant A edit\n")
            self.assertNotEqual(file_hashes(a), file_hashes(b))
            with self.assertRaises(FileExistsError):
                prepare(output)
            self.assertEqual((a / "site/app.js").read_text(), "// Participant A edit\n")


if __name__ == "__main__":
    unittest.main()
