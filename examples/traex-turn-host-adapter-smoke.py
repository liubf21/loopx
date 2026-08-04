#!/usr/bin/env python3
"""Smoke for the thin TraeX Turn host adapter.

Guards the reusable request/result translation without calling the model or
network: action-text extraction from the bounded Turn envelope, noise-stripping
and final-block parsing of TraeX stdout, result shaping, and acceptance by the
real LoopX host-result validator.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
for path in (str(REPO_ROOT), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import traex_turn_host_adapter as adapter  # noqa: E402
from loopx.control_plane.turn_driver.executor import (  # noqa: E402
    validate_loopx_turn_host_result,
)


TURN_KEY = (
    "sha256:" + "0" * 64
)


def _request(*, recommended_action: str = "Do the small thing.") -> dict:
    return {
        "schema_version": adapter.LOOPX_TURN_HOST_REQUEST_SCHEMA,
        "turn_key": TURN_KEY,
        "route": "primary_delivery",
        "session": {"goal_id": "g", "agent_id": "a"},
        "turn_envelope": {
            "goal_id": "g",
            "agent_id": "a",
            "action": {
                "recommended_action": recommended_action,
                "primary_action": None,
                "must_attempt": True,
            },
        },
        "result_contract": {
            "schema_version": adapter.LOOPX_TURN_RESULT_SCHEMA,
            "completed_phases": list(adapter.COMPLETED_PHASES),
        },
    }


def _plan(request: dict) -> dict:
    return {
        "transaction": {"turn_key": request["turn_key"]},
        "turn_envelope": request["turn_envelope"],
    }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_action_text_prefers_recommended_action() -> None:
    request = _request(recommended_action="the real task body")
    request["turn_envelope"]["action"]["primary_action"] = "ignored"
    _assert(
        adapter.extract_action_text(request) == "the real task body",
        "recommended_action must be the bounded task body",
    )


def test_action_text_falls_back_to_selected_todo() -> None:
    request = _request()
    request["turn_envelope"]["action"]["recommended_action"] = None
    request["turn_envelope"]["action"]["primary_action"] = None
    request["turn_envelope"]["action"]["selected_todo"] = {"text": "todo body"}
    _assert(
        adapter.extract_action_text(request) == "todo body",
        "selected_todo.text is the fallback task body",
    )


def test_parse_strips_hook_noise_and_reads_last_block() -> None:
    stdout = (
        "hook: pre-tool started\n"
        "INFO some transport line\n"
        "Here is my thinking.\n"
        "```json\n"
        + json.dumps(
            {
                "result_kind": "validated_progress",
                "classification": "updated config",
                "summary": "changed one field",
                "next_action": "run the smoke",
            }
        )
        + "\n```\n"
        "hook: post-tool done\n"
    )
    parsed = adapter.parse_result_block(stdout)
    _assert(parsed is not None, "final fenced block must parse")
    assert parsed is not None
    _assert(parsed["result_kind"] == "validated_progress", "kind preserved")


def test_parse_ignores_invalid_earlier_blocks() -> None:
    stdout = (
        "```json\n{not json}\n```\n"
        "trailing answer\n"
        "```json\n"
        + json.dumps(
            {
                "result_kind": "wait",
                "classification": "throttled",
                "summary": "no work due",
            }
        )
        + "\n```\n"
    )
    parsed = adapter.parse_result_block(stdout)
    _assert(parsed is not None and parsed["result_kind"] == "wait", "valid block wins")


def test_material_progress_result_validates() -> None:
    request = _request()
    candidate = {
        "result_kind": "validated_progress",
        "classification": "single surface change",
        "summary": "edited one file",
        "next_action": "review the diff",
    }
    result = adapter.build_result(request, candidate)
    verdict = validate_loopx_turn_host_result(_plan(request), result)
    _assert(verdict["ok"], "material result must validate: " + "; ".join(verdict["errors"]))


def test_wait_result_validates_without_material_fields() -> None:
    request = _request()
    result = adapter.build_result(
        request,
        {
            "result_kind": "wait",
            "classification": "throttled",
            "next_action": "retry after cadence",
        },
    )
    verdict = validate_loopx_turn_host_result(_plan(request), result)
    _assert(verdict["ok"], "wait result must validate: " + "; ".join(verdict["errors"]))
    _assert("delivery_batch_scale" not in result, "stop kinds carry no batch scale")


def test_missing_result_block_fails_closed_to_wait() -> None:
    request = _request()
    result = adapter.build_result(request, None, fallback_reason="no block found")
    _assert(result["result_kind"] == "wait", "missing block must not fabricate progress")
    verdict = validate_loopx_turn_host_result(_plan(request), result)
    _assert(verdict["ok"], "fail-closed wait must validate: " + "; ".join(verdict["errors"]))


def test_text_fields_are_bounded() -> None:
    request = _request()
    candidate = {
        "result_kind": "user_action_required",
        "classification": "x" * 500,
        "summary": "y" * 900,
        "next_action": "z" * 5000,
    }
    result = adapter.build_result(request, candidate)
    _assert(
        len(result["classification"]) <= 120,
        "classification must respect its limit",
    )
    _assert(len(result["summary"]) <= 400, "summary must respect its limit")
    _assert(len(result["next_action"]) <= 1_200, "next_action must respect its limit")


def test_subprocess_adapter_roundtrip_with_fake_host() -> None:
    """End-to-end: request JSON on stdin -> adapter -> valid result on stdout."""

    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "fake-traex"
        block = json.dumps(
            {
                "result_kind": "validated_progress",
                "classification": "did it",
                "summary": "one change",
                "next_action": "review",
            }
        )
        script = (
            "#!/bin/sh\n"
            'echo "hook: pre-tool"\n'
            'echo "INFO transport"\n'
            'echo "```json"\n'
            f"echo '{block}'\n"
            'echo "```"\n'
        )
        fake.write_text(script)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

        request = _request()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "traex_turn_host_adapter.py"),
                "--traex-bin",
                str(fake),
            ],
            input=json.dumps(request),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        _assert(completed.returncode == 0, "adapter must exit 0: " + completed.stderr)
        result = json.loads(completed.stdout)
        verdict = validate_loopx_turn_host_result(_plan(request), result)
        _assert(
            verdict["ok"],
            "roundtrip result must validate: " + "; ".join(verdict["errors"]),
        )


def main() -> int:
    tests = [
        test_action_text_prefers_recommended_action,
        test_action_text_falls_back_to_selected_todo,
        test_parse_strips_hook_noise_and_reads_last_block,
        test_parse_ignores_invalid_earlier_blocks,
        test_material_progress_result_validates,
        test_wait_result_validates_without_material_fields,
        test_missing_result_block_fails_closed_to_wait,
        test_text_fields_are_bounded,
        test_subprocess_adapter_roundtrip_with_fake_host,
    ]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
