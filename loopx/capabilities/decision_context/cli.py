from __future__ import annotations

import argparse
from collections.abc import Callable

from .architecture import build_decision_context_architecture_packet


def _render(payload: dict[str, object]) -> str:
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "decision_context"
    )
    return "\n".join(
        [
            "# Decision Context",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- packet_schemas: `{len(payload.get('packet_schemas') or [])}`",
            f"- source_schemas: `{len(payload.get('source_schemas') or [])}`",
            "",
        ]
    )


def register_decision_context_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "decision-context",
        help="Inspect the provider-neutral decision evidence and outcome contract.",
    )
    commands = parser.add_subparsers(dest="decision_context_command", required=True)
    architecture = commands.add_parser(
        "architecture",
        help="Render the default-off Stage-0 Decision Context contract.",
    )
    add_subcommand_format(architecture)


def handle_decision_context_command(
    args: argparse.Namespace,
    *,
    output_format: Callable[..., str],
    print_payload: Callable[[dict[str, object], str, Callable], None],
) -> int | None:
    if args.command != "decision-context":
        return None
    payload = build_decision_context_architecture_packet()
    print_payload(payload, output_format(args), _render)
    return 0
