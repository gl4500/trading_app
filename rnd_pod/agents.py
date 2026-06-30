"""Builders for the 4-agent R&D pod. Each *_agent() returns kwargs for
client.beta.agents.create; create_pod() persists them and returns the IDs."""
from __future__ import annotations
from rnd_pod.config import PodConfig

AGENT_TOOLSET = {"type": "agent_toolset_20260401"}

_SCOPE_RULE = (
    "HARD RULES: Operate ONLY inside the trading_app repo. Never read or write any "
    "polymarket_app path. Treat trading.db as READ-ONLY — open it via the read-only "
    "SQLite URI (file:...?mode=ro) and never write to it."
)


def researcher_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Quant Researcher",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Quant Researcher. Propose ONE falsifiable hypothesis and the "
            "CHEAPEST probe that could kill it. Run the probe on real local data using "
            f"the app runtime python at {cfg.runtime_python}. Report raw numbers — "
            f"{cfg.north_star}, plus IC and sample sizes — with no spin. Probe cheaply "
            "BEFORE proposing any build. " + _SCOPE_RULE
        ),
    }


def skeptic_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Red-Team Skeptic",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Red-Team Skeptic, independent of the Builder. Attack every probe "
            "for leakage, look-ahead, overfit, selection bias, regime artifact, and "
            "insufficient sample size. Issue an explicit GO or NO-GO ruling with reasons. "
            "Never loosen an honest falsifier to manufacture a GO — a clean NO-GO that "
            "prevents shipping noise is a success. " + _SCOPE_RULE
        ),
    }


def builder_agent(cfg: PodConfig) -> dict:
    return {
        "name": "Builder",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "system": (
            "You are the Builder. Engage ONLY on a GO ruling. Follow TDD strictly: write "
            "the failing test first, run it red, implement the minimal change, run the FULL "
            "test suite green, then report evidence (commands + output). Do not expand scope "
            "beyond the approved hypothesis. " + _SCOPE_RULE
        ),
    }


def lead_agent(cfg: PodConfig, roster_ids: list[str]) -> dict:
    return {
        "name": "Research Lead",
        "model": cfg.model,
        "tools": [AGENT_TOOLSET],
        "multiagent": {"type": "coordinator", "agents": list(roster_ids)},
        "system": (
            "You are the Research Lead and coordinator. Each iteration: (1) read "
            f"{cfg.ledger_path} (newest on top) and pick the next hypothesis; (2) delegate "
            "framing+probe to the Quant Researcher; (3) delegate critique to the Red-Team "
            "Skeptic; (4) referee GO/NO-GO judged on " + cfg.north_star + " — on NO-GO, "
            "append the verdict to the ledger and end the iteration; (5) on GO, delegate "
            "the build to the Builder (TDD); (6) independently verify before merge: full "
            "suite green, scope isolation held (NO polymarket_app paths in the diff), and "
            "trading.db SHA-256 unchanged; (7) merge to main only if all gates pass, then "
            "append the outcome to the ledger. Subagents do NOT share your history — pass "
            "everything they need in each delegated message. " + _SCOPE_RULE
        ),
    }


def create_pod(client, cfg: PodConfig) -> dict[str, str]:
    researcher = client.beta.agents.create(**researcher_agent(cfg))
    skeptic = client.beta.agents.create(**skeptic_agent(cfg))
    builder = client.beta.agents.create(**builder_agent(cfg))
    lead = client.beta.agents.create(
        **lead_agent(cfg, roster_ids=[researcher.id, skeptic.id, builder.id])
    )
    return {
        "researcher": researcher.id,
        "skeptic": skeptic.id,
        "builder": builder.id,
        "lead": lead.id,
    }
