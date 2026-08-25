"""Hermes Agent Runtime integration over its OpenAI-compatible HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from openai import AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from ..events import AgentAdapterCompleted, AgentAdapterEvent, AgentAdapterTextDelta
from ..models import AgentMessage, StartRunCommand, TokenUsage

STANDARD_FINISH_REASONS = {
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "function_call",
}


class HermesHttpAgentRuntime:
    """Run Hermes as an independently deployed OpenAI-compatible service."""

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

    async def run(self, command: StartRunCommand) -> AsyncIterator[AgentAdapterEvent]:
        completion = await self._client.chat.completions.create(
            model=await self._resolve_remote_model_id(),
            messages=[_to_openai_message(message) for message in command.messages],
            max_completion_tokens=command.options.max_output_tokens or omit,
            stream=False,
            temperature=(
                command.options.temperature if command.options.temperature is not None else omit
            ),
        )
        if not completion.choices:
            raise RuntimeError("Hermes returned a chat completion without choices")
        choice = completion.choices[0]
        content = choice.message.content
        if content is None:
            raise RuntimeError("Hermes returned a chat completion without assistant text")
        if content:
            yield AgentAdapterTextDelta(delta=content)
        finish_reason = str(choice.finish_reason)
        if finish_reason not in STANDARD_FINISH_REASONS:
            raise RuntimeError(f"Hermes agent run ended with finish reason: {finish_reason}")
        usage = completion.usage
        yield AgentAdapterCompleted(
            finish_reason=choice.finish_reason,
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
