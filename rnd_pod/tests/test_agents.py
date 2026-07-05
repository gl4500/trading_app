import unittest
from pathlib import Path
from rnd_pod.config import default_config
from rnd_pod.agents import (
    researcher_agent, skeptic_agent, builder_agent, lead_agent, AGENT_TOOLSET,
)


class TestAgents(unittest.TestCase):
    def setUp(self):
        self.cfg = default_config(Path("/c/Users/gl450/trading_app"))

    def test_each_agent_uses_model_and_toolset(self):
        for build in (researcher_agent, skeptic_agent, builder_agent):
            a = build(self.cfg)
            self.assertEqual(a["model"], "claude-opus-4-8")
            self.assertIn(AGENT_TOOLSET, a["tools"])
            self.assertTrue(a["system"].strip())

    def test_skeptic_system_demands_go_nogo(self):
        a = skeptic_agent(self.cfg)
        self.assertIn("GO", a["system"])
        self.assertIn("NO-GO", a["system"])

    def test_builder_system_requires_tdd(self):
        self.assertIn("TDD", builder_agent(self.cfg)["system"].upper().replace("TEST-DRIVEN", "TDD"))

    def test_lead_has_coordinator_roster(self):
        a = lead_agent(self.cfg, roster_ids=["agent_r", "agent_s", "agent_b"])
        self.assertEqual(a["multiagent"]["type"], "coordinator")
        self.assertEqual(a["multiagent"]["agents"], ["agent_r", "agent_s", "agent_b"])

    def test_lead_system_states_scope_and_db_invariants(self):
        sys_text = lead_agent(self.cfg, roster_ids=[])["system"]
        self.assertIn("polymarket_app", sys_text)   # scope isolation called out
        self.assertIn("trading.db", sys_text)        # read-only DB called out
        self.assertIn("realized PnL", sys_text)      # north star


if __name__ == "__main__":
    unittest.main()
