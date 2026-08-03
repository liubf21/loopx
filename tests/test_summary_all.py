from __future__ import annotations

import loopx.summary_all as summary_all


def test_blocked_visible_todo_is_not_counted_as_runnable(monkeypatch, tmp_path) -> None:
    status_payload = {
        "attention_queue": {
            "items": [{"goal_id": "blocked-goal", "waiting_on": "user"}],
        },
        "global_registry": {"findings": []},
    }
    quota_payload = {
        "goal_id": "blocked-goal",
        "state": "operator_gate",
        "recommended_action": "Wait for approval.",
        "agent_lane_next_action": {
            "todo_id": "todo-blocked",
            "text": "Run after approval.",
            "status": "open",
        },
        "user_todo_summary": {
            "open_count": 1,
            "items": [{"todo_id": "gate-1", "text": "Approve this run?"}],
        },
        "interaction_contract": {
            "user_channel": {
                "action_required": True,
                "question": "Approve this run?",
            },
        },
    }

    monkeypatch.setattr(summary_all, "collect_status", lambda **_: status_payload)
    monkeypatch.setattr(summary_all, "load_registry", lambda _: {})
    monkeypatch.setattr(summary_all, "resolve_runtime_root", lambda *_: tmp_path)
    monkeypatch.setattr(summary_all, "collect_history", lambda **_: {"runs": []})
    monkeypatch.setattr(
        summary_all,
        "build_quota_should_run",
        lambda *_args, **_kwargs: quota_payload,
    )

    payload = summary_all.build_summary_all(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        scan_roots=[],
        agent_id=None,
        time_range="24h",
        limit=5,
    )

    assert payload["groups"]["runnable_agent_work"] == []
    assert len(payload["todos"]) == 1
    assert payload["summary"]["runnable_todo_count"] == 0
