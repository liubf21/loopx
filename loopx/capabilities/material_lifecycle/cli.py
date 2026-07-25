from __future__ import annotations

import argparse
from collections.abc import Callable

from .architecture import build_material_lifecycle_architecture_packet


def _render(payload: dict[str, object]) -> str:
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "material_lifecycle"
    )
    return "\n".join(
        [
            "# Material Lifecycle",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- contract_schemas: `{len(payload.get('contract_schemas') or [])}`",
            "",
        ]
    )


def register_material_lifecycle_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "material-lifecycle",
        help="Inspect the backup-safe material inventory and rerank contract.",
    )
    commands = parser.add_subparsers(
        dest="material_lifecycle_command",
        required=True,
    )
    architecture = commands.add_parser(
        "architecture",
        help="Render the default-off Stage-0 Material Lifecycle contract.",
    )
    add_subcommand_format(architecture)


def handle_material_lifecycle_command(
    args: argparse.Namespace,
    *,
    output_format: Callable[..., str],
    print_payload: Callable[[dict[str, object], str, Callable], None],
) -> int | None:
    if args.command != "material-lifecycle":
        return None
    payload = build_material_lifecycle_architecture_packet()
    print_payload(payload, output_format(args), _render)
    return 0
