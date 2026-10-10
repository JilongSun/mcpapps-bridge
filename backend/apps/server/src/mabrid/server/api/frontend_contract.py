"""Offline export of the first-party frontend contract, without starting infrastructure."""

import argparse
import json
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from pydantic import JsonValue

from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.server.composition import GatewayManagementComposition

from .app import create_app
from .host import ERRORS
from .host_contracts import HostStreamEvent


def _schema_references(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
            references.add(reference.removeprefix("#/components/schemas/"))
        for child in value.values():
            references.update(_schema_references(child))
    elif isinstance(value, list):
        for child in value:
            references.update(_schema_references(child))
    return references


def frontend_contract(app: FastAPI | None = None) -> dict[str, JsonValue]:
    if app is None:
        app = create_app(
            cast(GatewaySessionCoordinator, object()),
            gateway_management=cast(GatewayManagementComposition, object()),
        )
    document = app.openapi()
    paths = {
        path: operation
        for path, operation in document["paths"].items()
        if path.startswith("/api/v1/") or path in {"/health", "/ready"}
    }
    definitions = document["components"]["schemas"]
    schemas: dict[str, Any] = {}
    pending = _schema_references(paths)
    while pending:
        name = pending.pop()
        if name in schemas:
            continue
        schemas[name] = definitions[name]
        pending.update(_schema_references(definitions[name]) - schemas.keys())
    return cast(
        dict[str, JsonValue],
        {
            "contract_version": "v0.1",
            "openapi": {
                "openapi": document["openapi"],
                "info": document["info"],
                "paths": paths,
                "components": {"schemas": schemas},
            },
            "host_sse": HostStreamEvent.model_json_schema(mode="serialization"),
            "host_errors": {
                code: {"status": status, "message": message}
                for code, (status, message) in ERRORS.items()
            },
            "stream": {
                "method": "POST",
                "media_type": "text/event-stream",
                "event_name": "event.kind",
                "event_id": "event_id",
                "sequence": "contiguous per Run, starting at 1",
                "terminal_kinds": ["run.completed", "run.cancelled", "run.failed"],
                "replay": False,
                "automatic_resubmission": False,
                "last_event_id": "rejected as unsupported_operation",
                "disconnect": "cleanup, not confirmed user cancellation",
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export or check the offline v0.1 frontend contract."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = frontend_contract()
    if args.check:
        if (
            not args.output.is_file()
            or json.loads(args.output.read_text(encoding="utf-8")) != document
        ):
            parser.exit(1, "Frontend contract differs from the committed snapshot.\n")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
