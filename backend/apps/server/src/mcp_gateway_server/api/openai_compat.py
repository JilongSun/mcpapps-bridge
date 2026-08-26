"""Inbound OpenAI-compatible HTTP adapter for the Agent Host application."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Body
from mcp_gateway_service.agent_host import (
    AgentHostService,
    AgentMessage,
    AgentRunError,
    GenerationOptions,
    StartRunCommand,
)
from openai.pagination import AsyncPage
from openai.types import Model
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.completion_create_params import CompletionCreateParams
from openai.types.completion_usage import CompletionUsage
from starlette.responses import JSONResponse


def create_openai_compatibility_router(agent_host: AgentHostService) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/models")
    async def list_models() -> JSONResponse:
        models = await agent_host.list_models()
        response = AsyncPage[Model](
            object="list",
            data=[
                Model(
                    id=model.model_id,
                    created=_timestamp(model.created_at),
                    object="model",
                    owned_by=model.owned_by,
                )
                for model in models
            ],
        )
        return JSONResponse(response.model_dump(mode="json", exclude_none=True))

    @router.post("/chat/completions")
    async def create_chat_completion(
        payload: CompletionCreateParams = Body(
            ...,
            openapi_examples={
                "basic": {
                    "summary": "Basic text completion",
                    "value": {
                        "model": agent_host.target.target_id,
                        "messages": [{"role": "user", "content": "Hello"}],
                        "stream": False,
                    },
                }
            },
        ),
    ) -> JSONResponse:
        try:
            command = _to_start_run_command(payload)
        except (TypeError, ValueError) as exc:
            return _error_response(str(exc), status_code=422, error_type="invalid_request_error")

        if payload.get("stream") is True:
            return _error_response(
                "Streaming chat completions are not implemented yet",
                status_code=400,
                error_type="invalid_request_error",
                param="stream",
            )

        try:
            result = await agent_host.complete(command)
        except AgentRunError as exc:
            return _error_response(str(exc), status_code=502, error_type="api_error")

        completion = ChatCompletion(
            id=f"chatcmpl-{result.run_id.hex}",
            choices=[
                Choice(
                    finish_reason=result.finish_reason,
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant",
                        content=result.output_text,
                    ),
                )
            ],
            created=int(datetime.now(timezone.utc).timestamp()),
            model=result.model,
            object="chat.completion",
            usage=CompletionUsage(
                completion_tokens=result.usage.output_tokens,
                prompt_tokens=result.usage.input_tokens,
                total_tokens=result.usage.total_tokens,
            ),
        )
        return JSONResponse(completion.model_dump(mode="json", exclude_none=True))

    return router


def _to_start_run_command(payload: Mapping[str, Any]) -> StartRunCommand:
    raw_messages = cast(Iterable[Mapping[str, Any]], payload["messages"])
    messages: list[AgentMessage] = []
    for message in raw_messages:
        role = message.get("role")
        content = message.get("content")
        if role == "tool":
            raise ValueError("Tool messages are not supported in this release")
        if role not in {"developer", "system", "user", "assistant"}:
            raise ValueError(f"Unsupported chat message role: {role}")
        if not isinstance(content, str):
            raise ValueError("Only text message content is supported in this release")
        name = message.get("name")
        messages.append(
            AgentMessage(
                role=role,
                content=content,
                name=name if isinstance(name, str) else None,
            )
        )

    max_output_tokens = payload.get("max_completion_tokens") or payload.get("max_tokens")
    temperature = payload.get("temperature")
    return StartRunCommand(
        run_id=uuid4(),
        model=str(payload["model"]),
        messages=tuple(messages),
        options=GenerationOptions(
            temperature=float(temperature) if temperature is not None else None,
            max_output_tokens=int(max_output_tokens) if max_output_tokens is not None else None,
        ),
    )


def _timestamp(value: datetime | None) -> int:
    return int(value.timestamp()) if value is not None else 0


def _error_response(
    message: str,
    *,
    status_code: int,
    error_type: str,
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": None,
            }
        },
    )
