#!/usr/bin/env python3
"""Prove typed PR review acknowledgements and heartbeat pre-quota reconciliation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loopx.capabilities.issue_fix.pr_gate_reconcile import (  # noqa: E402
    reconcile_issue_fix_pr_review,
)
from loopx.capabilities.issue_fix.pr_review_pre_quota import (  # noqa: E402
    reconcile_issue_fix_pr_reviews_before_quota,
)
from loopx.rollout_event_log import (  # noqa: E402
    append_rollout_event_once,
    build_rollout_event,
    rollout_event_log_path,
)
from loopx.status import parse_active_state_todos  # noqa: E402


def run_cli(
    args: list[str],
    *,
    registry_path: Path,
    runtime_root: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime_root),
            "--format",
            "json",
            *args,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def item(state_file: Path, todo_id: str) -> dict[str, Any]:
    projection = parse_active_state_todos(state_file.read_text(encoding="utf-8"))
    return next(
        value
        for value in projection["user_todos"]["items"]
        if value["todo_id"] == todo_id
    )


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="loopx-issue-fix-pr-review-heartbeat-"
    ) as tmpdir:
        project = Path(tmpdir)
        runtime_root = project / "runtime"
        registry_path = project / ".loopx" / "registry.json"
        state_file = (
            project / ".codex" / "goals" / "example-goal" / "ACTIVE_GOAL_STATE.md"
        )
        registry_path.parent.mkdir(parents=True)
        state_file.parent.mkdir(parents=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "common_runtime_root": str(runtime_root),
                    "goals": [
                        {
                            "id": "example-goal",
                            "status": "active",
                            "repo": str(project),
                            "state_file": (
                                ".codex/goals/example-goal/ACTIVE_GOAL_STATE.md"
                            ),
                            "adapter": {
                                "kind": "read_only_project_map_v0",
                                "status": "connected-read-only",
                            },
                            "coordination": {
                                "agent_model": "peer_v1",
                                "registered_agents": ["codex-test"],
                            },
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        state_file.write_text(
            "# Active Goal State\n\n"
            "## User Todo / Owner Review Reading Queue\n\n"
            "- [ ] Review the validated GitHub PR.\n"
            "  <!-- loopx:todo todo_id=todo_github_review status=open "
            "task_class=user_action bound_agent=codex-test -->\n\n"
            "- [ ] Review an unsupported provider PR.\n"
            "  <!-- loopx:todo todo_id=todo_gitlab_review status=open "
            "task_class=user_action bound_agent=codex-test -->\n\n"
            "## Agent Todo\n\n",
            encoding="utf-8",
        )

        ack_args = [
            "issue-fix",
            "pr-review-ack",
            "--url",
            "https://github.com/huangruiteng/loopx/pull/1716",
            "--goal-id",
            "example-goal",
            "--todo-id",
            "todo_github_review",
            "--agent-id",
            "codex-test",
            "--project",
            str(project),
            "--owner-acknowledged",
            "--generated-at",
            "2026-07-23T07:30:00Z",
        ]
        ack_result = run_cli(
            ack_args,
            registry_path=registry_path,
            runtime_root=runtime_root,
        )
        assert ack_result.returncode == 0, ack_result.stderr
        acknowledged = json.loads(ack_result.stdout)
        assert acknowledged["write_performed"] is True, acknowledged
        assert acknowledged["ack_receipt"]["readback_verified"] is True, acknowledged
        assert acknowledged["binding"]["pr_ref"] == ("huangruiteng/loopx#1716"), (
            acknowledged
        )

        repeated_ack = json.loads(
            run_cli(
                ack_args,
                registry_path=registry_path,
                runtime_root=runtime_root,
            ).stdout
        )
        assert repeated_ack["replayed"] is True, repeated_ack
        assert (
            repeated_ack["ack_receipt"]["receipt_id"]
            == (acknowledged["ack_receipt"]["receipt_id"])
        ), repeated_ack

        gitlab_event = build_rollout_event(
            goal_id="example-goal",
            event_kind="pr_review_ack",
            agent_id="codex-test",
            todo_id="todo_gitlab_review",
            run_id="group/project#12",
            pr_ref="group/project#12",
            status="acknowledged",
            details={
                "receipt_schema_version": "issue_fix_pr_review_ack_receipt_v0",
                "binding_schema_version": "issue_fix_pr_review_binding_v0",
                "provider": "gitlab",
                "repository": "group/project",
                "pr_number": 12,
                "permalink": "https://gitlab.com/group/project/-/merge_requests/12",
                "owner_acknowledged": True,
            },
            recorded_at="2026-07-23T07:31:00Z",
        )
        append_rollout_event_once(
            rollout_event_log_path(runtime_root, "example-goal"),
            gitlab_event,
            identity_fields=(
                "goal_id",
                "event_kind",
                "todo_id",
                "agent_id",
                "run_id",
            ),
        )

        no_network = reconcile_issue_fix_pr_reviews_before_quota(
            registry_path=registry_path,
            runtime_root=runtime_root,
            runtime_root_arg=str(runtime_root),
            goal_id="example-goal",
            agent_id="codex-test",
            project=project,
            available_capabilities=[],
            metadata_fetcher=lambda _binding: {
                "state": "MERGED",
                "mergedAt": "2026-07-23T07:32:00Z",
            },
        )
        assert no_network["status"] == "capability_unavailable", no_network
        assert no_network["external_read_performed"] is False, no_network

        open_hook = reconcile_issue_fix_pr_reviews_before_quota(
            registry_path=registry_path,
            runtime_root=runtime_root,
            runtime_root_arg=str(runtime_root),
            goal_id="example-goal",
            agent_id="codex-test",
            project=project,
            available_capabilities=["network"],
            metadata_fetcher=lambda _binding: {"state": "OPEN"},
        )
        assert open_hook["attempted_count"] == 1, open_hook
        assert open_hook["reconciled_count"] == 0, open_hook
        assert {value["status"] for value in open_hook["items"]} == {
            "pr_not_terminal",
            "unsupported_provider",
        }, open_hook

        mismatched_receipt = json.loads(json.dumps(acknowledged["ack_receipt"]))
        mismatched_receipt["binding"]["pr_number"] = 9999
        mismatch = reconcile_issue_fix_pr_review(
            registry_path=registry_path,
            runtime_root_arg=str(runtime_root),
            goal_id="example-goal",
            todo_id="todo_github_review",
            agent_id="codex-test",
            project=project,
            url="https://github.com/huangruiteng/loopx/pull/1716",
            ack_receipt=mismatched_receipt,
            provider_payload={
                "state": "MERGED",
                "mergedAt": "2026-07-23T07:32:00Z",
            },
            execute=True,
        )
        assert mismatch["skip_reason"] == "ack_receipt_binding_mismatch", mismatch
        assert mismatch["write_performed"] is False, mismatch

        fake_bin = project / "fake-bin"
        fake_bin.mkdir()
        fake_gh = fake_bin / "gh"
        unexpected_marker = project / "unexpected-gh-call"
        fake_gh.write_text(
            f"#!/bin/sh\ntouch {unexpected_marker}\nexit 99\n",
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)
        env = {
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        run_cli(
            [
                "quota",
                "should-run",
                "--goal-id",
                "example-goal",
                "--agent-id",
                "codex-test",
                "--available-capability",
                "network",
            ],
            registry_path=registry_path,
            runtime_root=runtime_root,
            env=env,
        )
        assert not unexpected_marker.exists()

        fake_gh.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' "
            """'{"state":"MERGED","mergedAt":"2026-07-23T07:33:00Z","reviewDecision":"APPROVED","statusCheckRollup":[],"url":"https://github.com/huangruiteng/loopx/pull/1716"}'"""
            "\n",
            encoding="utf-8",
        )
        heartbeat = run_cli(
            [
                "quota",
                "should-run",
                "--goal-id",
                "example-goal",
                "--agent-id",
                "codex-test",
                "--codex-app",
                "--turn-instance-id",
                "2026-07-23T07:34:00Z",
                "--available-capability",
                "network",
            ],
            registry_path=registry_path,
            runtime_root=runtime_root,
            env=env,
        )
        assert heartbeat.stdout.strip(), heartbeat.stderr
        quota = json.loads(heartbeat.stdout)
        hook = quota["pre_quota_reconciliation"]
        assert hook["reconciled_count"] == 1, quota
        assert hook["write_performed"] is True, quota
        assert hook["quota_decision_mutated"] is False, quota
        assert item(state_file, "todo_github_review")["status"] == "done"
        assert item(state_file, "todo_gitlab_review")["status"] == "open"

        repeated_hook = reconcile_issue_fix_pr_reviews_before_quota(
            registry_path=registry_path,
            runtime_root=runtime_root,
            runtime_root_arg=str(runtime_root),
            goal_id="example-goal",
            agent_id="codex-test",
            project=project,
            available_capabilities=["network"],
            metadata_fetcher=lambda _binding: (_ for _ in ()).throw(
                AssertionError("completed GitHub receipt must not fetch again")
            ),
        )
        assert repeated_hook["external_read_performed"] is False, repeated_hook
        assert repeated_hook["write_performed"] is False, repeated_hook
        assert [value["status"] for value in repeated_hook["items"]] == [
            "unsupported_provider"
        ], repeated_hook

    print("issue-fix-pr-review-heartbeat-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
