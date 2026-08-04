#!/usr/bin/env python3
"""Scheduler-hint-aware external worker for generic visible CLI loops.

This is a `shell_worker` connector (cron/launchd/service timer). It does NOT
replace the host TUI. On every tick it asks LoopX whether the registered agent
should run, projects a one-line public-safe status, and either:

  * observe-only (default): sleeps until the scheduler hint says to re-check;
  * with --wake-cmd: runs the configured command when should_run is true.

The generic CLI scheduler hint carries only the *initial* interval plus a
progression ladder and an unchanged-poll limit. Unlike codex-app's stateful
host backoff, the local progression index is not persisted server-side, so this
worker tracks consecutive unchanged polls in a small state file and advances
through the ladder exactly as a visible TUI loop would.

No raw transcripts, task text, credentials, or local absolute project paths are
emitted. The status line is the liveness signal.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEDULER_DETAIL_KEY = "local_scheduler"
TERMINAL_ACTIONS = frozenset({"stop_until_explicit_resume"})


@dataclass(frozen=True)
class TickDecision:
    should_run: bool
    action: str
    cadence_class: str
    reason: str
    interval_minutes: int
    progression: tuple[int, ...]
    unchanged_limit: int | None
    after_limit: str
    reset_token: str
    terminal: bool

    @property
    def sleep_seconds(self) -> int:
        return max(5, int(self.interval_minutes) * 60)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_local_scheduler(payload: dict[str, Any]) -> dict[str, Any]:
    hint = _mapping(payload.get("scheduler_hint"))
    detail = _mapping(hint.get("cold_path_detail"))
    local = _mapping(detail.get(SCHEDULER_DETAIL_KEY))
    if local:
        return local
    # Without --include-detail scheduler only the hot-path limit strings are
    # present; fail closed instead of inventing a cadence.
    raise ValueError(
        "scheduler_hint.cold_path_detail.local_scheduler missing; "
        "run quota should-run with --include-detail scheduler"
    )


def _extract_reset_token(payload: dict[str, Any]) -> str:
    reset_policy = _mapping(_mapping(payload.get("scheduler_hint")).get("reset_policy"))
    return str(reset_policy.get("reset_token") or "").strip()


def parse_tick(payload: dict[str, Any]) -> TickDecision:
    hint = _mapping(payload.get("scheduler_hint"))
    action = str(hint.get("action") or "").strip()
    local = _extract_local_scheduler(payload)

    progression_values = local.get("example_progression_minutes")
    progression: tuple[int, ...] = ()
    if isinstance(progression_values, (list, tuple)):
        progression = tuple(
            max(1, int(value)) for value in progression_values if str(value).strip()
        )
    initial = max(1, int(local.get("recommended_interval_minutes") or 1))
    if not progression:
        progression = (initial,)

    unchanged_limit_raw = local.get("unchanged_poll_limit")
    unchanged_limit = (
        int(unchanged_limit_raw)
        if unchanged_limit_raw is not None and str(unchanged_limit_raw).strip()
        else None
    )
    after_limit = str(local.get("after_limit") or "continue").strip() or "continue"

    cadence_class = str(hint.get("cadence_class") or "").strip()
    reason = str(hint.get("reason") or payload.get("state") or "").strip()
    should_run = bool(payload.get("should_run"))

    return TickDecision(
        should_run=should_run,
        action=action,
        cadence_class=cadence_class,
        reason=reason,
        interval_minutes=initial,
        progression=progression,
        unchanged_limit=unchanged_limit,
        after_limit=after_limit,
        reset_token=_extract_reset_token(payload),
        terminal=action in TERMINAL_ACTIONS,
    )


def run_quota_should_run(command_prefix: Sequence[str]) -> dict[str, Any]:
    completed = subprocess.run(
        list(command_prefix),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"quota should-run exited {completed.returncode}: {error[:500]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"quota should-run returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("quota should-run returned a non-object payload")
    return payload


def _load_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(path: Path | None, state: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def select_interval(
    decision: TickDecision,
    *,
    unchanged_count: int,
) -> tuple[int, str]:
    if decision.should_run:
        return decision.interval_minutes, "active"
    index = min(max(0, unchanged_count), len(decision.progression) - 1)
    return decision.progression[index], f"unchanged#{index + 1}"


def _log(line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {line}", flush=True)


def _run_wake(command: str) -> int:
    completed = subprocess.run(command, shell=True, check=False)
    return completed.returncode


def build_should_run_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.cli_bin,
        "--format",
        "json",
        "--registry",
        str(args.registry),
    ]
    if args.runtime_root:
        command.extend(["--runtime-root", str(args.runtime_root)])
    command.extend(
        [
            "quota",
            "should-run",
            "--goal-id",
            args.goal_id,
            "--agent-id",
            args.agent_id,
            "--runtime-profile",
            args.runtime_profile,
            "--include-detail",
            "scheduler",
        ]
    )
    return command


def run_worker(args: argparse.Namespace) -> int:
    should_run_command = build_should_run_command(args)
    state_path = Path(args.state_file).expanduser() if args.state_file else None
    once = bool(args.once)

    while True:
        state = _load_state(state_path)
        previous_token = str(state.get("reset_token") or "")
        unchanged_count = int(state.get("unchanged_count") or 0)

        try:
            payload = run_quota_should_run(should_run_command)
            decision = parse_tick(payload)
        except (RuntimeError, ValueError) as exc:
            _log(f"status=tick_error error={shlex.quote(str(exc))}")
            if once:
                return 2
            time.sleep(max(5, args.error_backoff_seconds))
            continue

        if decision.reset_token and decision.reset_token != previous_token:
            unchanged_count = 0

        interval_minutes, phase = select_interval(
            decision, unchanged_count=unchanged_count
        )

        effective_action = str(payload.get("effective_action") or "").strip()
        selected = _mapping(payload.get("selected_todo"))
        selected_id = str(selected.get("todo_id") or "").strip()

        if decision.terminal:
            _log(
                "status=terminal "
                f"action={decision.action} class={decision.cadence_class} "
                f"reason={shlex.quote(decision.reason)}"
            )
            _save_state(
                state_path,
                {"reset_token": decision.reset_token, "unchanged_count": 0},
            )
            return 0

        if decision.should_run:
            wake_status = "would_wake"
            wake_rc = None
            if args.wake_cmd:
                wake_rc = _run_wake(args.wake_cmd)
                wake_status = "wake_ok" if wake_rc == 0 else "wake_failed"
            _log(
                f"status=should_run {wake_status} "
                f"action={decision.action} class={decision.cadence_class} "
                f"effective_action={effective_action or '-'} "
                f"todo={selected_id or '-'} "
                f"reason={shlex.quote(decision.reason)}"
                + (f" wake_rc={wake_rc}" if wake_rc is not None else "")
            )
            unchanged_count = 0
        else:
            _log(
                "status=waiting "
                f"phase={phase} class={decision.cadence_class} "
                f"effective_action={effective_action or '-'} "
                f"next_check_minutes={interval_minutes} "
                f"unchanged_count={unchanged_count}"
                + (
                    f" unchanged_limit={decision.unchanged_limit}"
                    if decision.unchanged_limit is not None
                    else ""
                )
                + f" reason={shlex.quote(decision.reason)}"
            )
            unchanged_count += 1
            at_limit = (
                decision.unchanged_limit is not None
                and unchanged_count >= decision.unchanged_limit
            )
            if at_limit and decision.after_limit == "stop_tick_loop":
                _save_state(
                    state_path,
                    {
                        "reset_token": decision.reset_token,
                        "unchanged_count": unchanged_count,
                    },
                )
                _log(
                    "status=stop_after_unchanged_limit "
                    f"unchanged_limit={decision.unchanged_limit} "
                    "next=explicit_resume_or_fresh_evidence"
                )
                return 0

        _save_state(
            state_path,
            {
                "reset_token": decision.reset_token,
                "unchanged_count": unchanged_count,
            },
        )

        if once:
            return 0
        time.sleep(max(5, interval_minutes * 60))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scheduler-hint-aware external shell_worker for generic CLI loops.",
    )
    parser.add_argument("--cli-bin", default="loopx", help="LoopX CLI binary.")
    parser.add_argument(
        "--registry",
        default=str(Path.home() / ".codex" / "loopx" / "registry.global.json"),
        help="Path to the LoopX registry.",
    )
    parser.add_argument("--runtime-root", help="Override registry common_runtime_root.")
    parser.add_argument(
        "--runtime-profile",
        default="generic_cli",
        help="Quota runtime profile that emits the local_scheduler hint "
        "(generic_cli for generic visible CLI loops such as TraeX/OpenCode).",
    )
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument(
        "--state-file",
        help="Where to persist the unchanged-poll progression index "
        "(e.g. ~/.loopx/external-worker/<goal>-<agent>.json).",
    )
    parser.add_argument(
        "--wake-cmd",
        help="Optional shell command to run when should_run is true. "
        "Without it the worker is observe-only.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit instead of sleeping and looping.",
    )
    parser.add_argument(
        "--error-backoff-seconds",
        type=float,
        default=60.0,
        help="Sleep between failed quota should-run invocations when looping.",
    )
    args = parser.parse_args(argv)
    return run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
