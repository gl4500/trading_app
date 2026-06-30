import unittest
from rnd_pod.kickoff import _kickoff_text, DEFAULT_KICKOFF


class TestKickoffText(unittest.TestCase):
    def test_next_returns_default_ledger_driven_kickoff(self):
        self.assertEqual(_kickoff_text("next"), DEFAULT_KICKOFF)

    def test_default_names_closed_hypotheses_to_avoid(self):
        # Guards against re-litigating the falsified H12/H13 and the fixed H1.
        for closed in ("H1", "H12", "H13"):
            self.assertIn(closed, DEFAULT_KICKOFF)

    def test_explicit_hypothesis_is_embedded_and_guarded(self):
        text = _kickoff_text("H4")
        self.assertIn("H4", text)
        # Even an explicit target reminds the Lead the closed ones are off-limits.
        self.assertIn("CLOSED", text)

    def test_explicit_hypothesis_is_not_the_default(self):
        self.assertNotEqual(_kickoff_text("H4"), DEFAULT_KICKOFF)


if __name__ == "__main__":
    unittest.main()
