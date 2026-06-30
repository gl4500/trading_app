"""Self-hosted environment helpers."""
from __future__ import annotations


def self_hosted_env_kwargs(name: str) -> dict:
    return {"name": name, "config": {"type": "self_hosted"}}


def ensure_environment(client, name: str) -> str:
    for env in client.beta.environments.list():
        if env.name == name:
            return env.id
    return client.beta.environments.create(**self_hosted_env_kwargs(name)).id
