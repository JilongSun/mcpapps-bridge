"""Frozen first-party schemas and examples, separate from runtime wire protocols."""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import httpx
import pytest
from httpx_sse import EventSource
from pydantic import BaseModel
from sse_starlette import ServerSentEvent

from mabrid.application.gateway.sessions import GatewaySessionCoordinator
from mabrid.application.agent_host import (
    AgentHistoryPage,
    RuntimeCapabilityObservation,
    EffectiveCapability,
)
from mabrid.server.api import create_app
from mabrid.server.composition import GatewayManagementComposition
from mabrid.server.api.capabilities import ProductCapabilitiesResponse
from mabrid.server.api.host_contracts import (
    CreateHostSessionRequest,
    StartHostSessionRunRequest,
    HostSessionResponse,
    HostSessionPageResponse,
    HostErrorResponse,
    HostStopResponse,
    HostReconcileResponse,
    HostStreamEvent,
)
from mabrid.server.api.management.errors import ProblemDetails

from mabrid.server.api.frontend_contract import frontend_contract

CONTRACT_ROOT = Path(__file__).resolve().parents[4] / "docs" / "contracts" / "v0.1"
EXAMPLES = json.loads((CONTRACT_ROOT / "examples.json").read_text(encoding="utf-8"))
EXAMPLE_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        CreateHostSessionRequest,
        StartHostSessionRunRequest,
        HostSessionResponse,
        HostSessionPageResponse,
        AgentHistoryPage,
        HostErrorResponse,
        HostStopResponse,
        HostReconcileResponse,
        HostStreamEvent,
        ProductCapabilitiesResponse,
        RuntimeCapabilityObservation,
        EffectiveCapability,
        ProblemDetails,
    )
}


@pytest.mark.parametrize("example", EXAMPLES, ids=[example["name"] for example in EXAMPLES])
def test_frozen_examples_validate_against_public_models_and_sse_encoding(example: dict) -> None:
    model = EXAMPLE_MODELS[example["schema"]].model_validate(example["value"])
    assert json.loads(model.model_dump_json()) == example["value"]
    if isinstance(model, HostStreamEvent):
        wire = ServerSentEvent(
            event=model.event.kind, id=str(model.event_id), data=model.model_dump_json()
        ).encode()
        response = httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)
        frames = list(EventSource(response).iter_sse())
        assert len(frames) == 1 and frames[0].event == model.event.kind
        assert frames[0].id == str(model.event_id)
        assert HostStreamEvent.model_validate_json(frames[0].data) == model


def test_examples_cover_every_stream_payload_and_effective_availability() -> None:
    kinds = {
        example["value"]["event"]["kind"]
        for example in EXAMPLES
        if example["schema"] == "HostStreamEvent"
    }
    assert kinds == set(
        HostStreamEvent.model_json_schema()["properties"]["event"]["discriminator"]["mapping"]
    )
    example_by_name = {example["name"]: example["value"] for example in EXAMPLES}
    success = [
        example_by_name[name]
        for name in (
            "run-started",
            "tool-started",
            "tool-completed",
            "widget-created",
            "assistant-delta",
            "assistant-text-completed",
            "run-completed",
        )
    ]
    assert [event["sequence"] for event in success] == list(range(1, 8))
    assert (
        len({event["session_id"] for event in success})
        == len({event["run_id"] for event in success})
        == 1
    )
    assert (
        example_by_name["tool-started"]["event"]["tool_invocation_id"]
        == example_by_name["widget-created"]["event"]["widget"]["tool_invocation_id"]
    )
    assert example_by_name["runtime-owned-history"]["has_more"] is None
    assert example_by_name["stop-accepted-not-terminal"]["settlement"] == "unconfirmed"
    assert {"available", "unavailable", "unknown", "unsupported"} == {
        example["value"]["availability"]
        for example in EXAMPLES
        if example["schema"] == "EffectiveCapability"
    }


def test_committed_contract_matches_current_schemas_and_has_no_dangling_references() -> None:
    document = json.loads((CONTRACT_ROOT / "frontend-contract.json").read_text(encoding="utf-8"))
    assert document == frontend_contract()

    def verify(value: object, root: dict) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                assert reference.startswith("#/")
                resolved = root
                for segment in reference.removeprefix("#/").split("/"):
                    resolved = resolved[segment.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                verify(child, root)
        elif isinstance(value, list):
            for child in value:
                verify(child, root)

    verify(document["openapi"], document["openapi"])
    verify(document["host_sse"], document["host_sse"])


def test_offline_contract_check_detects_drift(tmp_path: Path) -> None:
    output = tmp_path / "contract.json"
    command = [sys.executable, "-m", "mabrid.server.api.frontend_contract", str(output)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    subprocess.run([*command, "--check"], check=True, capture_output=True, text=True)
    changed = json.loads(output.read_text(encoding="utf-8"))
    changed["stream"]["replay"] = True
    output.write_text(json.dumps(changed), encoding="utf-8")
    result = subprocess.run([*command, "--check"], check=False, capture_output=True, text=True)
    assert result.returncode == 1
    assert "differs from the committed snapshot" in result.stderr


def test_offline_frontend_contract_is_deterministic_and_partitions_routes() -> None:
    contract = frontend_contract()
    assert contract == frontend_contract()
    document = json.loads(json.dumps(contract))
    paths = document["openapi"]["paths"]
    assert set(paths) == {
        "/api/v1/host/sessions",
        "/api/v1/host/sessions/{session_id}",
        "/api/v1/host/sessions/{session_id}/history",
        "/api/v1/host/sessions/{session_id}/runs",
        "/api/v1/host/sessions/{session_id}/runs/{run_id}/cancel",
        "/api/v1/host/sessions/{session_id}/runs/{run_id}/reconcile",
        "/api/v1/capabilities",
        "/api/v1/gateway/status",
        "/api/v1/gateway/topology",
        "/api/v1/gateway/sessions",
        "/api/v1/gateway/sessions/{session_id}",
        "/api/v1/gateway/sessions/{session_id}/snapshot",
        "/api/v1/gateway/sessions/{session_id}/events",
        "/api/v1/agent-host/target",
        "/health",
        "/ready",
    }
    run = paths["/api/v1/host/sessions/{session_id}/runs"]["post"]
    assert set(run["responses"]["200"]["content"]) == {"text/event-stream"}
    for status in ("404", "409", "422", "500", "502", "503"):
        assert set(run["responses"][status]["content"]) == {"application/json"}
    assert all(
        set(operation) == {"get"}
        for path, operation in paths.items()
        if path.startswith(("/api/v1/gateway", "/api/v1/agent-host"))
    )
    host_schemas = json.dumps(document["host_sse"])
    for private in (
        "session_key",
        "operation_key",
        "runtime_binding_id",
        "remote_session_id",
        "remote_run_id",
    ):
        assert private not in host_schemas
    assert "CompletionCreateParams" not in json.dumps(contract)
    assert document["host_sse"]["properties"]["event"]["discriminator"]["propertyName"] == "kind"
    assert document["stream"]["replay"] is False
    for path in ("/api/v1/gateway/sessions", "/api/v1/agent-host/target"):
        assert set(paths[path]["get"]["responses"]["422"]["content"]) == {
            "application/problem+json"
        }
    assert set(paths["/ready"]["get"]["responses"]["503"]["content"]) == {
        "application/problem+json"
    }


async def test_management_errors_match_the_frozen_media_type_and_safe_validation() -> None:
    app = create_app(
        cast(GatewaySessionCoordinator, object()),
        gateway_management=cast(GatewayManagementComposition, object()),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture.test"
    ) as client:
        for path, status, code in (
            ("/api/v1/gateway/sessions?limit=0", 422, "invalid_request"),
            ("/api/v1/agent-host/target", 404, "agent_host_disabled"),
        ):
            response = await client.get(path)
            assert response.status_code == status
            assert response.headers["content-type"] == "application/problem+json"
            assert response.json()["code"] == code
            schema = app.openapi()["paths"][path.split("?")[0]]["get"]["responses"][str(status)][
                "content"
            ]["application/problem+json"]["schema"]
            assert set(response.json()) == set(schema["properties"])
