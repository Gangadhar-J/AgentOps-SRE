import logging
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider
from agentops.llm.mock_provider import MockRuleBasedLLMProvider
from agentops.llm.gemini import GeminiLLMProvider
from agentops.llm.openai_provider import OpenAILLMProvider

logger = logging.getLogger("agentops.llm.factory")


def get_llm_provider(provider_override: str | None = None) -> BaseLLMProvider:
    """
    Factory resolving the LLM provider based on configuration or environment availability.
    """
    provider = (provider_override or settings.LLM_PROVIDER).lower().strip()

    if provider == "gemini" or (provider == "auto" and settings.GEMINI_API_KEY):
        if settings.GEMINI_API_KEY:
            logger.info("Initializing Gemini LLM Provider")
            return GeminiLLMProvider(api_key=settings.GEMINI_API_KEY, model_name=settings.LLM_MODEL)
        logger.warning("GEMINI_API_KEY requested but not found. Falling back to Mock provider.")

    if provider == "openai" or (provider == "auto" and settings.OPENAI_API_KEY):
        if settings.OPENAI_API_KEY:
            logger.info("Initializing OpenAI LLM Provider")
            return OpenAILLMProvider(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                model_name=settings.LLM_MODEL,
            )
        logger.warning("OPENAI_API_KEY requested but not found. Falling back to Mock provider.")

    # Default to MockRuleBasedLLMProvider for deterministic local testing
    logger.info("Using Deterministic Rule-Based Mock LLM Provider")
    return MockRuleBasedLLMProvider()
