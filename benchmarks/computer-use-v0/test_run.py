"""Scoring regressions for observable computer-use outcomes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from run import code_for, outcome_reached, score_case, window_for


class ComputerUseScoringTests(unittest.TestCase):
    def test_seed_replays_same_case_inputs_across_models(self) -> None:
        self.assertEqual(code_for("comparison", "form", 1), code_for("comparison", "form", 1))
        self.assertNotEqual(code_for("comparison", "form", 1), code_for("comparison", "form", 2))

    def test_window_selection_uses_cua_title_and_pid(self) -> None:
        windows = {"windows": [
            {"pid": 11, "title": "Computer Use Eval: button", "window_id": 5, "is_on_screen": True},
            {"pid": 12, "title": "Computer Use Eval: button", "window_id": 6, "is_on_screen": True},
        ]}
        with patch("run.plugin_command", return_value=windows):
            self.assertEqual(window_for("python", {}, 12, "button", 1), 6)

    def test_model_claim_without_action_does_not_pass_button(self) -> None:
        state = {"caseID": "button", "nonce": "ABC123", "recordCount": 0,
                 "resetCount": 0, "cancelCount": 0}
        run = {"status": "finished", "needsObservation": False, "observationCount": 1,
               "actionCount": 0, "result": "I clicked Record."}
        self.assertTrue(score_case("button", "ABC123", state, run))

    def test_correct_button_action_passes(self) -> None:
        state = {"caseID": "button", "nonce": "ABC123", "recordCount": 1,
                 "resetCount": 0, "cancelCount": 0}
        run = {"status": "finished", "needsObservation": False, "observationCount": 2,
               "actionCount": 1, "result": "Recorded"}
        self.assertEqual(score_case("button", "ABC123", state, run), [])

    def test_distractor_action_fails(self) -> None:
        state = {"caseID": "button", "nonce": "ABC123", "recordCount": 1,
                 "resetCount": 1, "cancelCount": 0}
        run = {"status": "finished", "needsObservation": False, "observationCount": 3,
               "actionCount": 2, "result": "Recorded"}
        self.assertTrue(score_case("button", "ABC123", state, run))

    def test_form_requires_submitted_value_and_final_observation(self) -> None:
        state = {"caseID": "form", "nonce": "ABC123", "submitCount": 1,
                 "submittedText": "ABC12", "discardCount": 0}
        run = {"status": "finished", "needsObservation": True, "observationCount": 1,
               "actionCount": 2, "result": "Done"}
        failures = score_case("form", "ABC123", state, run)
        self.assertEqual(len(failures), 2)

    def test_timeout_preserves_reached_outcome_separately_from_pass(self) -> None:
        state = {"caseID": "form", "nonce": "ABC123", "submitCount": 1,
                 "submittedText": "ABC123", "discardCount": 0}
        run = {"status": "timed-out", "needsObservation": False, "observationCount": 3,
               "actionCount": 2, "result": None}
        self.assertTrue(outcome_reached("form", "ABC123", state, run))
        self.assertIn("plugin run did not finish", score_case("form", "ABC123", state, run))

    def test_read_only_case_needs_exact_report(self) -> None:
        state: dict[str, object] = {"caseID": "read-code", "nonce": "ABC123"}
        run = {"status": "finished", "needsObservation": False, "observationCount": 1,
               "actionCount": 0, "result": "ABC124"}
        self.assertTrue(score_case("read-code", "ABC123", state, run))


if __name__ == "__main__":
    unittest.main()
