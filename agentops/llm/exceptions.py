"""
Typed LLM Error Taxonomy for AgentOps-SRE.
Maps provider-specific failures into stable, structured internal error categories.
"""

class LLMError(Exception):
    """Base exception for all LLM provider and inference errors."""
    def __init__(self, message: str, provider: str = "unknown", model: str = "unknown", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model
        self.details = details or {}

    @property
    def error_category(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict:
        return {
            "error_category": self.error_category,
            "message": self.message,
            "provider": self.provider,
            "model": self.model,
            "details": self.details,
        }


class ProviderUnavailableError(LLMError):
    """Raised when the provider endpoint is unreachable or connection is refused."""


class ModelNotFoundError(LLMError):
    """Raised when the requested model tag does not exist in the provider's inventory."""


class InferenceTimeoutError(LLMError):
    """Raised when LLM reasoning exceeds the configured timeout."""


class InvalidModelOutputError(LLMError):
    """Raised when LLM output cannot be parsed as valid JSON or fails schema validation."""


class EvidenceValidationError(LLMError):
    """Raised when the model references non-existent or fabricated evidence IDs."""


class ProviderAuthenticationError(LLMError):
    """Raised when API key or authentication credentials are invalid or missing."""


class RateLimitError(LLMError):
    """Raised when the provider rejects inference due to rate or quota limits."""
