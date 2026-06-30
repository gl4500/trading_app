"""Create a session for one hypothesis and drain its event stream (stream-first)."""
from __future__ import annotations
from rnd_pod.config import PodConfig
from rnd_pod.environment import self_hosted_env_kwargs, ensure_environment  # noqa: F401 (re-export)


def is_terminal(event_type: str, stop_reason_type: str | None = None) -> bool:
    if event_type == "session.status_terminated":
        return True
    if event_type == "session.status_idle" and stop_reason_type != "requires_action":
        return True
    return False


def _stop_reason_type(event) -> str | None:
    sr = getattr(event, "stop_reason", None)
    return getattr(sr, "type", None) if sr is not None else None


def run_iteration(client, cfg: PodConfig, lead_id: str, env_id: str, kickoff_text: str) -> None:
    session = client.beta.sessions.create(agent=lead_id, environment_id=env_id)
    print(f"session {session.id} — "
          f"https://platform.claude.com/workspaces/default/sessions/{session.id}")
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message",
                     "content": [{"type": "text", "text": kickoff_text}]}],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in getattr(event, "content", []) or []:
                    if getattr(block, "type", None) == "text":
                        print(block.text, end="", flush=True)
            if is_terminal(event.type, _stop_reason_type(event)):
                break
