from __future__ import annotations

import pytest

from loopx.cli import build_parser, main, output_format, resolve_global_output_format


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--goal-id", "example-goal", "--project", "."],
        ["quota", "should-run", "--goal-id", "example-goal", "--project", "."],
    ],
)
def test_unsupported_project_option_is_not_misparsed_as_projection_cache_ttl(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "unrecognized arguments: --project ." in stderr
    assert "projection-cache-ttl-seconds" not in stderr
    assert "invalid int value" not in stderr


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["quota", "should-run"], "json"),
        (["quota", "status"], "markdown"),
        (["status"], "markdown"),
        (["diagnose"], "markdown"),
        (["review-packet", "--goal-id", "example-goal"], "markdown"),
    ],
)
def test_only_quota_should_run_defaults_to_json(
    argv: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(argv)

    assert resolve_global_output_format(args) == expected


@pytest.mark.parametrize("explicit_format", ["markdown", "json"])
def test_explicit_global_format_overrides_quota_should_run_default(
    explicit_format: str,
) -> None:
    args = build_parser().parse_args(
        ["--format", explicit_format, "quota", "should-run"]
    )

    assert resolve_global_output_format(args) == explicit_format


def test_subcommand_format_keeps_precedence_over_resolved_global_default() -> None:
    args = build_parser().parse_args(["status", "--format", "json"])
    args.format = resolve_global_output_format(args)

    assert output_format(args) == "json"
