"""Hermes-specific outbound Agent Runtime integration."""

from .capability_document import HermesCapabilityDocument
from .chat_completions import HermesChatCompletionsAdapter

__all__ = ["HermesCapabilityDocument", "HermesChatCompletionsAdapter"]
