"""Hermes runtime adapter for its OpenAI-compatible Chat Completions API."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import cast

from openai import AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from ...contracts import (
    AgentAdapterCompleted,
    AgentAdapterEvent,
    AgentAdapterTextDelta,
    AgentCapability,
    AgentFinishReason,
    AgentMessage,
    AgentRuntimeInterface,
    AgentRuntimeProfile,
    StartRunCommand,
    TokenUsage,
)
from .capability_document import HermesCapabilityDocument

STANDARD_FINISH_REASONS = {
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "function_call",
}
HERMES_CHAT_COMPLETIONS_PROFILE = AgentRuntimeProfile(
    integration_kind="hermes",
    interface=AgentRuntimeInterface.OPENAI_CHAT_COMPLETIONS,
    capabilities=frozenset(
        {
            AgentCapability.TEXT_GENERATION,
            AgentCapability.TOKEN_USAGE,
        }
    ),
)


class HermesChatCompletionsAdapter:
    """Run Hermes through its independently deployed Chat Completions API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 120.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout_seconds,
        )
        self._remote_model_id: str | None = None

    @property
    def profile(self) -> AgentRuntimeProfile:
        return HERMES_CHAT_COMPLETIONS_PROFILE

    async def fetch_capability_document(self) -> HermesCapabilityDocument:
        return await self._client.get(
            "/capabilities",
            cast_to=HermesCapabilityDocument,
        )

    async def run(self, command: StartRunCommand) -> AsyncGenerator[AgentAdapterEvent, None]:
        stream = await self._client.chat.completions.create(
            model=await self._resolve_remote_model_id(),
            messages=[_to_openai_message(message) for message in command.messages],
            max_completion_tokens=command.options.max_output_tokens or omit,
            stream=True,
            stream_options={"include_usage": True},
            temperature=(
                command.options.temperature if command.options.temperature is not None else omit
            ),
        )
        finish_reason: AgentFinishReason | None = None
        usage = None
        received_text = False
        async with stream:
            async for chunk in stream:
                if chunk.usage is not None:
                    usage = chunk.usage
                for choice in chunk.choices:
                    if choice.index != 0:
                        continue
                    content = choice.delta.content
                    if content is not None:
                        received_text = True
                        if content:
                            yield AgentAdapterTextDelta(delta=content)
                    if choice.finish_reason is not None:
                        reason = str(choice.finish_reason)
                        if reason not in STANDARD_FINISH_REASONS:
                            raise RuntimeError(
                                f"Hermes agent run ended with finish reason: {reason}"
                            )
                        finish_reason = cast(AgentFinishReason, reason)
        if not received_text:
            raise RuntimeError("Hermes returned a chat completion without assistant text")
        if finish_reason is None:
            raise RuntimeError("Hermes chat completion stream ended without a finish reason")
        yield AgentAdapterCompleted(
            finish_reason=finish_reason,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage is not None else 0,
                output_tokens=usage.completion_tokens if usage is not None else 0,
            ),
        )

    async def close(self) -> None:
        await self._client.close()

    async def _resolve_remote_model_id(self) -> str:
        if self._remote_model_id is not None:
            return self._remote_model_id
        page = await self._client.models.list()
        models = page.data
        if len(models) != 1:
            raise RuntimeError(
                f"Hermes Agent Target requires exactly one model, received {len(models)}"
            )
        self._remote_model_id = models[0].id
        return self._remote_model_id


def _to_openai_message(message: AgentMessage) -> ChatCompletionMessageParam:
    if message.role == "tool":
        raise ValueError("Hermes tool messages are not supported in this release")
    payload: dict[str, object] = {
        "role": "system" if message.role == "developer" else message.role,
        "content": message.content,
    }
    if message.name is not None:
        payload["name"] = message.name
    return cast(ChatCompletionMessageParam, payload)
