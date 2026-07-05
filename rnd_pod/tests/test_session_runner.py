import unittest
from rnd_pod.session_runner import is_terminal, self_hosted_env_kwargs


class TestSessionRunner(unittest.TestCase):
    def test_terminated_is_terminal(self):
        self.assertTrue(is_terminal("session.status_terminated"))

    def test_idle_end_turn_is_terminal(self):
        self.assertTrue(is_terminal("session.status_idle", "end_turn"))

    def test_idle_requires_action_is_not_terminal(self):
        self.assertFalse(is_terminal("session.status_idle", "requires_action"))

    def test_agent_message_is_not_terminal(self):
        self.assertFalse(is_terminal("agent.message"))

    def test_env_kwargs(self):
        self.assertEqual(
            self_hosted_env_kwargs("trading-app-rnd"),
            {"name": "trading-app-rnd", "config": {"type": "self_hosted"}},
        )


if __name__ == "__main__":
    unittest.main()
