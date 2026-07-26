from types import SimpleNamespace

from scripts.skillsbench_automation_loop import (
    DEFAULT_HOST_LOCAL_CODEX_BRIDGE_IDLE_TIMEOUT_SEC,
    HOST_LOCAL_ACP_AGENT_TIMEOUT_MARGIN_SEC,
    _effective_local_codex_exec_timeout_sec,
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
