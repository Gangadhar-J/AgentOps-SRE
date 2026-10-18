import logging
from typing import Optional

from agentops.config import settings
from agentops.llm.base import BaseLLMProvider
from agentops.llm.gemini import GeminiLLMProvider
from agentops.llm.openai_provider import OpenAILLMProvider
from agentops.llm.exceptions import ProviderUnavailableError

logger = logging.getLogger("agentops.llm.factory")


def get_llm_provider(provider_override: Optional[str] = None, model_override: Optional[str] = None) -> BaseLLMProvider:
    """
    Factory resolving the LLM provider based on explicit configuration.
    Never silently falls back to a mock or deterministic provider in live paths.
    """
    provider = (provider_override or settings.LLM_PROVIDER or "ollama").lower().strip()
    model = model_override or settings.LLM_MODEL or None

    if provider == "gemini":
        return GeminiLLMProvider(api_key=settings.GEMINI_API_KEY, model_name=model)

    if provider == "openai":
        return OpenAILLMProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            model_name=model or "gpt-4o",
        )

    if provider == "ollama":
        return OpenAILLMProvider(
            base_url=f"{settings.OLLAMA_URL.rstrip('/')}/v1",
            model_name=model or "qwen3.5:2b",
        )

    if provider == "auto":
        if settings.GEMINI_API_KEY:
            return GeminiLLMProvider(api_key=settings.GEMINI_API_KEY, model_name=model)
        if settings.OPENAI_API_KEY:
            return OpenAILLMProvider(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                model_name=model or "gpt-4o",
            )
        # Default to local Ollama runtime
        return OpenAILLMProvider(
            base_url=f"{settings.OLLAMA_URL.rstrip('/')}/v1",
            model_name=model or "qwen3.5:2b",
        )

    raise ProviderUnavailableError(
        f"Unsupported or unconfigured LLM provider: '{provider}'. Supported providers: 'ollama', 'gemini', 'openai'.",
        provider=provider,
        model=model or "unknown",
    )
