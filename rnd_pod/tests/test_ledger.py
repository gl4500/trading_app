import tempfile
import unittest
from pathlib import Path
from rnd_pod.ledger import format_verdict, append_verdict


class TestLedger(unittest.TestCase):
    def test_format_verdict_contains_fields(self):
        block = format_verdict(
            hypothesis_id="H12",
            claim="Porting the XGB bear gate to rule agents stops bear bleed.",
            probe="Re-score rule-agent bear closes with the gate applied.",
            numbers="bear PnL -19.3K -> -4.1K (244 closes)",
            verdict="GO",
            rationale="Survives leakage check; bear-only, no bull degradation.",
            date="2026-06-21",
        )
        self.assertIn("H12", block)
        self.assertIn("GO", block)
        self.assertIn("-19.3K", block)
        self.assertIn("2026-06-21", block)

    def test_append_verdict_puts_entry_after_h1(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ledger.md"
            p.write_text("# Model Improvement Ledger\n\nOLD ENTRY\n", encoding="utf-8")
            append_verdict(p, "NEW ENTRY BLOCK")
            text = p.read_text(encoding="utf-8")
            self.assertLess(text.index("NEW ENTRY BLOCK"), text.index("OLD ENTRY"))
            self.assertTrue(text.startswith("# Model Improvement Ledger"))


if __name__ == "__main__":
    unittest.main()
