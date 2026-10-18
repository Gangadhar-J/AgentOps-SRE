import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import requests

from agentops.config import settings
from agentops.llm.base import BaseLLMProvider, RCA_SYSTEM_PROMPT
from agentops.llm.exceptions import (
    ProviderUnavailableError,
    ModelNotFoundError,
    InferenceTimeoutError,
    ProviderAuthenticationError,
    RateLimitError,
    InvalidModelOutputError,
    EvidenceValidationError,
)
from agentops.models.evidence import InvestigationContext
from agentops.models.rca import RootCauseAnalysis

logger = logging.getLogger("agentops.llm.gemini")


class GeminiLLMProvider(BaseLLMProvider):
    """
    Gemini LLM Provider using Google AI Studio REST API.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            raise ProviderAuthenticationError(
                "GEMINI_API_KEY is not configured. Please export GEMINI_API_KEY=<your-key> or set it in your .env file.",
                provider="gemini",
                model=model_name or settings.LLM_MODEL or "gemini-1.5-flash",
            )
        self.model_name = model_name or settings.LLM_MODEL or "gemini-1.5-flash"
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"

    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        start_time = time.time()
        context_json = context.model_dump_json(indent=2)
        user_prompt = f"Analyze the following InvestigationContext and generate an RCA JSON:\n\n{context_json}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": RCA_SYSTEM_PROMPT},
                        {"text": user_prompt},
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key.startswith("AQ.") or self.api_key.startswith("ya29."):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["x-goog-api-key"] = self.api_key

        try:
            res = requests.post(self.endpoint, headers=headers, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
        except requests.exceptions.ConnectionError as e:
            raise ProviderUnavailableError(
                f"Gemini API endpoint unreachable: {str(e)}",
                provider="gemini",
                model=self.model_name,
            ) from e
        except requests.exceptions.Timeout as e:
            raise InferenceTimeoutError(
                f"Gemini inference timed out after {settings.LLM_TIMEOUT_SECONDS}s",
                provider="gemini",
                model=self.model_name,
            ) from e
        except Exception as e:
            raise ProviderUnavailableError(
                f"Unexpected error communicating with Gemini API: {str(e)}",
                provider="gemini",
                model=self.model_name,
            ) from e

        if not res.ok:
            error_body = res.text[:500]
            if res.status_code in (401, 403):
                raise ProviderAuthenticationError(
                    f"Authentication failed for Gemini API (HTTP {res.status_code})",
                    provider="gemini",
                    model=self.model_name,
                )
            if res.status_code == 404:
                raise ModelNotFoundError(
                    f"Gemini model '{self.model_name}' not found: {error_body}",
                    provider="gemini",
                    model=self.model_name,
                )
            if res.status_code == 429:
                raise RateLimitError(
                    f"Rate limit exceeded for Gemini API: {error_body}",
                    provider="gemini",
                    model=self.model_name,
                )
            raise InvalidModelOutputError(
                f"Gemini API returned HTTP {res.status_code}: {error_body}",
                provider="gemini",
                model=self.model_name,
                details={"status_code": res.status_code},
            )

        try:
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise InvalidModelOutputError(
                f"Malformed response structure from Gemini API: {str(e)}",
                provider="gemini",
                model=self.model_name,
            ) from e

        rca = self._validate_and_parse_rca(raw_text, context.investigation_id)

        # Independent evidence reference validation
        valid_evidence_ids = {item.id for item in context.evidence_items}
        if rca.evidence_ids:
            invalid_ids = [eid for eid in rca.evidence_ids if eid not in valid_evidence_ids]
            if invalid_ids:
                raise EvidenceValidationError(
                    f"Model generated invalid/unsupported evidence references: {invalid_ids}. Valid IDs: {sorted(list(valid_evidence_ids))}",
                    provider="gemini",
                    model=self.model_name,
                    details={"invalid_evidence_ids": invalid_ids, "valid_evidence_ids": sorted(list(valid_evidence_ids))},
                )

        metadata = {
            "provider": "gemini",
            "model": self.model_name,
            "latency_seconds": round(time.time() - start_time, 3),
            "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount"),
            "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount"),
            "time_to_first_token": None,
        }
        return rca, metadata
