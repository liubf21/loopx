"""Thin one-shot goal activation contract for Ark Managed Agent."""

from __future__ import annotations

from typing import Any


ARK_MANAGED_AGENT_HOST = "ark-managed-agent"
ARK_MANAGED_AGENT_HOST_CONTRACT_SCHEMA_VERSION = (
    "loopx_ark_managed_agent_goal_host_v0"
)
ARK_MANAGED_AGENT_PROMPT_FAMILY = "loopx_goal_prompt_v0"


def build_ark_managed_agent_host_contract() -> dict[str, Any]:
    """Describe transport-neutral ownership for one goal prompt activation."""

    return {
        "schema_version": ARK_MANAGED_AGENT_HOST_CONTRACT_SCHEMA_VERSION,
        "host_kind": ARK_MANAGED_AGENT_HOST,
        "activation_mode": "goal_once",
        "prompt_family": ARK_MANAGED_AGENT_PROMPT_FAMILY,
        "policy_source": "quota_should_run.interaction_contract",
        "transport_contract": "goal_prompt_v0",
        "goal_runtime_owns_continuation": True,
        "loopx_turn_driver_required": False,
        "session_state_authoritative": False,
    }
