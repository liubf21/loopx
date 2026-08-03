from __future__ import annotations

import argparse

QUOTA_SHOULD_RUN_DETAIL_SECTIONS = (
    "scheduler",
    "agent-todos",
    "user-todos",
    "goal-boundary",
    "vision",
)
QUOTA_MONITOR_POLL_DETAIL_SECTIONS = ("decisions",)
QUOTA_DETAIL_SECTIONS = (
    *QUOTA_SHOULD_RUN_DETAIL_SECTIONS,
    *QUOTA_MONITOR_POLL_DETAIL_SECTIONS,
)


def validate_quota_command_request(args: argparse.Namespace) -> None:
    command = args.quota_command
    if command not in {"status", "plan"} and not args.goal_id:
        raise ValueError(f"`loopx quota {command}` requires --goal-id")
    scheduler_commands = {
        "scheduler-ack",
        "scheduler-ack-current",
        "scheduler-fail-current",
    }
    if command in scheduler_commands and not args.agent_id:
        raise ValueError(f"`loopx quota {command}` requires --agent-id")
    if command == "void-slot" and not args.void_generated_at:
        raise ValueError("`loopx quota void-slot` requires --void-generated-at")
    if (
        command not in {"status", "plan", "should-run"}
        and args.dry_run
        and args.execute
    ):
        raise ValueError(
            f"`loopx quota {command}` accepts only one of --dry-run or --execute"
        )


def quota_detail_sections_from_args(args: argparse.Namespace) -> frozenset[str]:
    sections = set(getattr(args, "include_details", None) or ())
    if bool(getattr(args, "include_scheduler_detail", False)):
        sections.add("scheduler")
    if "all" in sections:
        sections.update(
            QUOTA_MONITOR_POLL_DETAIL_SECTIONS
            if args.quota_command == "monitor-poll"
            else QUOTA_SHOULD_RUN_DETAIL_SECTIONS
        )
        sections.discard("all")
    return frozenset(sections)
