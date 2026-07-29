from __future__ import annotations

from loopx.control_plane.scheduler.execution_context import (
    scheduler_execution_context_for_runtime_profile,
)
from loopx.control_plane.work_items.interaction_contract import (
    build_interaction_contract,
)


GOAL_ID = "runtime-capability-reentry-fixture"
AGENT_ID = "managed-agent"
MANAGED_AGENT_CONTEXT = scheduler_execution_context_for_runtime_profile(
    "ark_managed_agent_goal"
)


def _blocked_payload(*, missing: list[str]) -> dict:
    return {
        "goal_id": GOAL_ID,
        "agent_identity": {
            "agent_id": AGENT_ID,
            "agent_model": "peer_v1",
        },
        "should_run": True,
        "effective_action": "capability_bridge_repair",
        "execution_obligation": {
            "must_attempt_work": True,
            "delivery_allowed": False,
        },
        "heartbeat_recommendation": {
            "recommended_mode": "repair_capability_bridge",
        },
        "capability_gate": {
            "action": "repair_bridge",
            "repair_missing": missing,
            "owner_missing": [],
            "resolution_bindings": [
                {
                    "owner": "agent",
                    "action": "repair_bridge",
                    "capability": capability,
                    "priority": "P0",
                    "primary_blocked_todo_id": "todo_blocked",
                    "blocked_todo_ids": ["todo_blocked"],
                }
                for capability in missing
            ],
            "runnable_candidates": [],
        },
    }


def test_runtime_capability_gap_returns_verified_reentry_packet() -> None:
    contract = build_interaction_contract(
        _blocked_payload(missing=["network"]),
        available_capabilities=["shell"],
        scheduler_execution_context=MANAGED_AGENT_CONTEXT,
    )

    reentry = contract["cli_channel"]["runtime_capability_reentry"]
    assert reentry["schema_version"] == "runtime_capability_reentry_v0"
    assert reentry["state"] == "verification_required"
    assert reentry["inheritance_contract"] == {
        "source_invocation": "verified quota should-run reentry",
        "propagates_to": [
            "interaction_contract.cli_channel.next_cli_actions",
            "quota spend-slot",
            "quota monitor-poll",
        ],
        "session_scoped": True,
        "durable_grant_written": False,
    }
    candidate = reentry["candidates"][0]
    assert candidate["capability"] == "network"
    assert candidate["verification_required"] == (
        "successful_real_callsite_observation"
    )
    assert candidate["cli_args"] == [
        "loopx",
        "--format",
        "json",
        "quota",
        "should-run",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
        "--available-capability",
        "shell",
        "--available-capability",
        "network",
        "--runtime-profile",
        "ark_managed_agent_goal",
    ]
    assert any(
        action.startswith("after real-callsite verification of network:")
        for action in contract["cli_channel"]["next_cli_actions"]
    )


def test_verified_reentry_inherits_capability_into_followup_actions() -> None:
    contract = build_interaction_contract(
        {
            **_blocked_payload(missing=[]),
            "effective_action": "bounded_delivery",
            "execution_obligation": {
                "must_attempt_work": True,
                "delivery_allowed": True,
            },
            "capability_gate": {
                "action": "run",
                "repair_missing": [],
                "owner_missing": [],
                "resolution_bindings": [],
                "runnable_candidates": [
                    {
                        "todo_id": "todo_network",
                        "target_capabilities": ["network"],
                    }
                ],
            },
        },
        available_capabilities=["network"],
        scheduler_execution_context=MANAGED_AGENT_CONTEXT,
    )

    assert "runtime_capability_reentry" not in contract["cli_channel"]
    actions = contract["cli_channel"]["next_cli_actions"]
    assert actions
    assert all(
        "--available-capability network" in action
        for action in actions
        if action.startswith("loopx refresh-state")
        or action.startswith("loopx quota spend-slot")
    )


def test_owner_capability_never_becomes_runtime_reentry_candidate() -> None:
    contract = build_interaction_contract(
        _blocked_payload(missing=["credentials"]),
        available_capabilities=[],
        scheduler_execution_context=MANAGED_AGENT_CONTEXT,
    )

    assert "runtime_capability_reentry" not in contract["cli_channel"]
