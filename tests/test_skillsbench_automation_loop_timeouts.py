import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import skillsbench_automation_loop as skillsbench_loop
from scripts.skillsbench_automation_loop import (
    DEFAULT_HOST_LOCAL_CODEX_BRIDGE_IDLE_TIMEOUT_SEC,
    HOST_LOCAL_ACP_AGENT_TIMEOUT_MARGIN_SEC,
    SkillsBenchLoopXTurnTerminalFailureStall,
    _await_benchflow_task_with_loopx_turn_closeout_watchdog,
    _effective_local_codex_exec_timeout_sec,
    _loopx_turn_terminal_failure_checkpoint,
)


def _host_local_args(**overrides):
    values = {
        "agent_idle_timeout": 900,
        "host_local_acp_launch": True,
        "local_codex_bridge_idle_timeout_sec": None,
        "local_codex_exec_timeout_sec": None,
        "outer_timeout_sec": 0,
        "route": "loopx-product-mode",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_host_local_exec_timeout_defaults_to_bridge_idle_margin() -> None:
    assert _effective_local_codex_exec_timeout_sec(_host_local_args()) == (
        DEFAULT_HOST_LOCAL_CODEX_BRIDGE_IDLE_TIMEOUT_SEC
        + HOST_LOCAL_ACP_AGENT_TIMEOUT_MARGIN_SEC
    )


def test_host_local_exec_timeout_covers_outer_runner_timeout() -> None:
    assert (
        _effective_local_codex_exec_timeout_sec(
            _host_local_args(outer_timeout_sec=10800)
        )
        == 10800
    )


def test_host_local_exec_timeout_preserves_explicit_override() -> None:
    assert (
        _effective_local_codex_exec_timeout_sec(
            _host_local_args(
                local_codex_exec_timeout_sec=3600,
                outer_timeout_sec=10800,
            )
        )
        == 3600
    )


def test_host_local_exec_timeout_uses_outer_floor_when_bridge_idle_disabled() -> None:
    assert (
        _effective_local_codex_exec_timeout_sec(
            _host_local_args(
                local_codex_bridge_idle_timeout_sec=0,
                outer_timeout_sec=10800,
            )
        )
        == 10800
    )


def _terminal_turn_plan(
    tmp_path,
    *,
    committed: bool = False,
    process_failure: bool = True,
):
    boundary = {
        "raw_command_recorded": False,
        "raw_stdout_recorded": False,
        "raw_stderr_recorded": False,
        "raw_task_text_recorded": False,
        "raw_verifier_output_recorded": False,
        "raw_logs_recorded": False,
        "raw_trajectory_recorded": False,
        "credential_values_recorded": False,
        "host_paths_recorded": False,
        "remote_paths_recorded": False,
        "upload_performed": False,
        "submit_performed": False,
    }
    if process_failure:
        (tmp_path / "001-process.compact.json").write_text(
            json.dumps(
                {
                    "schema_version": (
                        "skillsbench_host_local_acp_relay_public_trace_v0"
                    ),
                    "trace_kind": "codex_exec_process_failure",
                    "codex_exec_process": {
                        "failure_category": "codex_exec_bridge_idle_timeout",
                        "recoverable_turn_failure": True,
                    },
                    "boundary": boundary,
                }
            ),
            encoding="utf-8",
        )
    (tmp_path / "002-turn.compact.json").write_text(
        json.dumps(
            {
                "schema_version": "skillsbench_host_local_acp_relay_public_trace_v0",
                "trace_kind": "loopx_turn_execution",
                "loopx_turn_execution": {
                    "schema_version": "loopx_turn_execution_v0",
                    "status": "committed" if committed else "failed",
                    "result_kind": (
                        "validated_completion" if committed else "repair_required"
                    ),
                    "validation": {
                        "status": "passed" if committed else "not_attempted"
                    },
                    "receipt": {
                        "status": "committed" if committed else "failed",
                        "result_kind": (
                            "validated_completion" if committed else "repair_required"
                        ),
                        "failed_phase": "" if committed else "host_execute",
                    },
                    "effects": {
                        "host_invoked": True,
                        "state_written": committed,
                        "quota_spent": committed,
                        "scheduler_acknowledged": committed,
                    },
                },
                "scored_workspace_validation": {
                    "status": "passed" if committed else "not_attempted",
                    "independent": True,
                },
                "boundary": boundary,
            }
        ),
        encoding="utf-8",
    )
    return {
        "route": "loopx-turn-agent-cli",
        "host_local_acp_relay_trace_dir": str(tmp_path),
        "job_name": "skillsbench-turn-watchdog-fixture",
        "rollout_name": "turn-watchdog-fixture",
        "runner_prerequisites": {
            "host_local_acp_launch": True,
            "agent_execution_mode": "host_local_acp",
        },
    }


def test_loopx_turn_terminal_failure_checkpoint_requires_stranded_process_failure(
    tmp_path,
) -> None:
    plan = _terminal_turn_plan(tmp_path)
    checkpoint = _loopx_turn_terminal_failure_checkpoint(plan)

    assert checkpoint == {
        "schema_version": "skillsbench_loopx_turn_terminal_failure_checkpoint_v0",
        "status": "failed",
        "result_kind": "repair_required",
        "failed_phase": "host_execute",
        "failure_category": "codex_exec_bridge_idle_timeout",
        "durable_effects_observed": False,
        "raw_material_recorded": False,
    }
    assert str(tmp_path) not in json.dumps(checkpoint, sort_keys=True)


def test_loopx_turn_terminal_failure_checkpoint_ignores_committed_turn(
    tmp_path,
) -> None:
    plan = _terminal_turn_plan(tmp_path, committed=True)
    assert _loopx_turn_terminal_failure_checkpoint(plan) is None


def test_loopx_turn_terminal_failure_checkpoint_waits_without_process_failure(
    tmp_path,
) -> None:
    plan = _terminal_turn_plan(tmp_path, process_failure=False)
    assert _loopx_turn_terminal_failure_checkpoint(plan) is None


def test_loopx_turn_terminal_failure_watchdog_cancels_stranded_benchflow(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _terminal_turn_plan(tmp_path)
    cleanup_calls = []

    def fake_cleanup(plan_arg):
        cleanup_calls.append(plan_arg["job_name"])
        return {"status": "no_matching_processes"}

    monkeypatch.setattr(
        skillsbench_loop,
        "cleanup_host_local_acp_attempt_children",
        fake_cleanup,
    )

    async def invoke() -> None:
        task = asyncio.create_task(asyncio.Event().wait())
        with pytest.raises(SkillsBenchLoopXTurnTerminalFailureStall):
            await _await_benchflow_task_with_loopx_turn_closeout_watchdog(
                task,
                plan,
                grace_seconds=0,
                poll_interval_seconds=0.01,
                cancel_timeout_seconds=0.1,
            )
        assert task.cancelled()

    asyncio.run(invoke())
    prerequisites = plan["runner_prerequisites"]
    assert (
        prerequisites["benchflow_loopx_turn_terminal_failure_watchdog_enabled"] is True
    )
    assert prerequisites["benchflow_loopx_turn_terminal_failure_observed"] is True
    assert prerequisites["benchflow_loopx_turn_terminal_failure_triggered"] is True
    assert (
        prerequisites["benchflow_loopx_turn_terminal_failure_task_cancel_acknowledged"]
        is True
    )
    assert (
        prerequisites["benchflow_loopx_turn_terminal_failure_raw_material_recorded"]
        is False
    )
    public = skillsbench_loop._public_runner_prerequisites(prerequisites)
    assert public["benchflow_loopx_turn_terminal_failure_triggered"] is True
    assert public["benchflow_loopx_turn_terminal_failure_grace_sec"] == 0
    assert public["benchflow_loopx_turn_terminal_failure_category"] == (
        "codex_exec_bridge_idle_timeout"
    )
    assert cleanup_calls == [plan["job_name"]]


def test_loopx_turn_terminal_failure_watchdog_preserves_final_verifier(
    tmp_path,
) -> None:
    plan = _terminal_turn_plan(tmp_path)
    plan["runner_prerequisites"]["benchflow_final_verifier_started"] = True

    async def invoke() -> str:
        async def finish_official_verifier() -> str:
            await asyncio.sleep(0.02)
            return "official-result"

        task = asyncio.create_task(finish_official_verifier())
        return await _await_benchflow_task_with_loopx_turn_closeout_watchdog(
            task,
            plan,
            grace_seconds=0,
            poll_interval_seconds=0.01,
            cancel_timeout_seconds=0.1,
        )

    assert asyncio.run(invoke()) == "official-result"
    assert (
        plan["runner_prerequisites"].get(
            "benchflow_loopx_turn_terminal_failure_triggered"
        )
        is not True
    )
