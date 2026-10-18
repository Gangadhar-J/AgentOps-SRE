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

logger = logging.getLogger("agentops.llm.openai")

_RCA_JSON_SCHEMA = """\
Output ONLY a valid JSON object — no markdown fences, no commentary, no <think> blocks.
Required fields:
{
  "investigation_id": "<copy from context>",
  "incident_type": "<CrashLoopBackOff|HighErrorRate|ResourceExhaustion|BadDeployment|Unknown>",
  "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
  "summary": "<one-sentence summary of the incident>",
  "root_cause": "<evidence-backed diagnosis>",
  "confidence": <float 0.0-1.0>,
  "evidence_ids": ["<only IDs that exist in the context, e.g. E001>"],
  "timeline": [{"timestamp": "<ISO8601>", "source": "<kubernetes|prometheus|loki>", "description": "<event>"}],
  "recommended_action": "<actionable remediation steps>",
  "requires_human_approval": true,
  "telemetry_coverage": {"kubernetes": <bool>, "prometheus": <bool>, "loki": <bool>}
}
"""

_THINKING_MODEL_PREFIXES = ("qwen3", "qwq", "deepseek-r1", "marco-o1")
_OPENAI_CLOUD_HOSTS = {"api.openai.com", "openai.azure.com"}


def _is_cloud_openai(base_url: str) -> bool:
    return any(h in base_url for h in _OPENAI_CLOUD_HOSTS)


def _is_thinking_model(model_name: str) -> bool:
    name = model_name.lower()
    return any(name.startswith(p) or f"/{p}" in name for p in _THINKING_MODEL_PREFIXES)


def _build_compact_context(context: InvestigationContext) -> str:
    data = context.model_dump()
    evidence = data.get("evidence_items", [])
    evidence = evidence[-8:]
    for item in evidence:
        item.pop("raw_payload", None)
        if isinstance(item.get("observation"), str) and len(item["observation"]) > 200:
            item["observation"] = item["observation"][:200] + "…"
    compact = {
        "investigation_id": data["investigation_id"],
        "namespace": data["namespace"],
        "workload": data["workload"],
        "telemetry_status": {k: {"available": v["available"]} for k, v in data.get("telemetry_status", {}).items()},
        "evidence_items": evidence,
    }
    return json.dumps(compact, indent=2, default=str)


class OpenAILLMProvider(BaseLLMProvider):
    """
    OpenAI / Ollama-compatible LLM Provider.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY or "local"
        self.base_url = (base_url or settings.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self.model_name = model_name or settings.LLM_MODEL or ("gpt-4o-mini" if _is_cloud_openai(self.base_url) else "qwen3.5:2b")
        self._is_cloud = _is_cloud_openai(self.base_url)
        self._is_thinking = not self._is_cloud and _is_thinking_model(self.model_name)

    def _verify_ollama_model(self) -> None:
        """Verify that the requested model exists in Ollama before sending inference request."""
        if self._is_cloud:
            return
        root_url = self.base_url.rsplit("/v1", 1)[0]
        try:
            res = requests.get(f"{root_url}/api/tags", timeout=2.5)
            if res.status_code == 200:
                data = res.json()
                models = [m.get("name") for m in data.get("models", [])]
                if self.model_name not in models:
                    matches = [m for m in models if m == self.model_name or m == f"{self.model_name}:latest" or (":" not in self.model_name and m.startswith(f"{self.model_name}:"))]
                    if not matches:
                        raise ModelNotFoundError(
                            f"Model '{self.model_name}' not found in Ollama inventory at {root_url}. Available models: {models}",
                            provider="ollama",
                            model=self.model_name,
                        )
        except requests.exceptions.ConnectionError as e:
            raise ProviderUnavailableError(
                f"Ollama server is unavailable at {root_url}: Connection refused",
                provider="ollama",
                model=self.model_name,
            ) from e
        except requests.exceptions.Timeout as e:
            raise InferenceTimeoutError(
                f"Ollama model discovery timed out at {root_url}",
                provider="ollama",
                model=self.model_name,
            ) from e

    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        start_time = time.time()
        provider_label = "openai" if self._is_cloud else "ollama"

        # Pre-execution model verification for Ollama
        self._verify_ollama_model()

        if self._is_cloud:
            context_body = context.model_dump_json(indent=2)
            user_content = f"Analyze the following InvestigationContext and generate an RCA JSON:\n\n{context_body}"
        else:
            context_body = _build_compact_context(context)
            user_content = (
                f"Analyze the InvestigationContext below and return an RCA.\n\n"
                f"{_RCA_JSON_SCHEMA}\n"
                f"InvestigationContext:\n{context_body}"
            )
            if self._is_thinking:
                user_content += "\n/no_think"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": RCA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "stream": False,
        }

        if self._is_cloud:
            payload["response_format"] = {"type": "json_object"}

        if self._is_thinking:
            payload["options"] = {"think": False}

        logger.info(
            f"Sending RCA request to {'Cloud OpenAI' if self._is_cloud else 'Local Ollama'} "
            f"| model={self.model_name} thinking_model={self._is_thinking} "
            f"| context=~{len(user_content)//1000}KB | timeout={settings.LLM_TIMEOUT_SECONDS}s"
        )

        try:
            res = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        except requests.exceptions.ConnectionError as e:
            raise ProviderUnavailableError(
                f"{provider_label.capitalize()} endpoint is unreachable at {self.base_url}: Connection refused",
                provider=provider_label,
                model=self.model_name,
            ) from e
        except requests.exceptions.Timeout as e:
            raise InferenceTimeoutError(
                f"{provider_label.capitalize()} inference timed out after {settings.LLM_TIMEOUT_SECONDS}s",
                provider=provider_label,
                model=self.model_name,
            ) from e
        except Exception as e:
            raise ProviderUnavailableError(
                f"Unexpected error communicating with {provider_label}: {str(e)}",
                provider=provider_label,
                model=self.model_name,
            ) from e

        if not res.ok:
            error_body = res.text[:500]
            if res.status_code in (401, 403):
                raise ProviderAuthenticationError(
                    f"Authentication failed for {provider_label} (HTTP {res.status_code})",
                    provider=provider_label,
                    model=self.model_name,
                )
            if res.status_code == 404:
                raise ModelNotFoundError(
                    f"Model '{self.model_name}' not found at {self.base_url} (HTTP 404): {error_body}",
                    provider=provider_label,
                    model=self.model_name,
                )
            if res.status_code == 429:
                raise RateLimitError(
                    f"Rate limit exceeded for {provider_label} (HTTP 429): {error_body}",
                    provider=provider_label,
                    model=self.model_name,
                )
            raise InvalidModelOutputError(
                f"{provider_label.capitalize()} API returned HTTP {res.status_code}: {error_body}",
                provider=provider_label,
                model=self.model_name,
                details={"status_code": res.status_code},
            )

        try:
            data = res.json()
            raw_text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise InvalidModelOutputError(
                f"Malformed response structure from {provider_label}: {str(e)}",
                provider=provider_label,
                model=self.model_name,
            ) from e

        if "<think>" in raw_text and "</think>" in raw_text:
            raw_text = raw_text[raw_text.rfind("</think>") + len("</think>"):].strip()

        rca = self._validate_and_parse_rca(raw_text, context.investigation_id)

        # Independent evidence reference validation
        valid_evidence_ids = {item.id for item in context.evidence_items}
        if rca.evidence_ids:
            invalid_ids = [eid for eid in rca.evidence_ids if eid not in valid_evidence_ids]
            if invalid_ids:
                raise EvidenceValidationError(
                    f"Model generated invalid/unsupported evidence references: {invalid_ids}. Valid IDs: {sorted(list(valid_evidence_ids))}",
                    provider=provider_label,
                    model=self.model_name,
                    details={"invalid_evidence_ids": invalid_ids, "valid_evidence_ids": sorted(list(valid_evidence_ids))},
                )

        metadata = {
            "provider": provider_label,
            "model": self.model_name,
            "latency_seconds": round(time.time() - start_time, 3),
            "prompt_tokens": data.get("usage", {}).get("prompt_tokens"),
            "completion_tokens": data.get("usage", {}).get("completion_tokens"),
            "time_to_first_token": None,
        }
        return rca, metadata
