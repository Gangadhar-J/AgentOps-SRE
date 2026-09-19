import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import requests
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider, RCA_SYSTEM_PROMPT
from agentops.models.evidence import InvestigationContext
from agentops.models.rca import RootCauseAnalysis

logger = logging.getLogger("agentops.llm.openai")

# Compact RCA JSON schema injected directly into the prompt for local models
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

# Models known to use internal chain-of-thought / thinking (qwen3, qwq, deepseek-r1, etc.)
# They support /no_think suffix to disable it and respond directly.
_THINKING_MODEL_PREFIXES = ("qwen3", "qwq", "deepseek-r1", "marco-o1")

# Only real OpenAI cloud endpoints support response_format=json_object
_OPENAI_CLOUD_HOSTS = {"api.openai.com", "openai.azure.com"}


def _is_cloud_openai(base_url: str) -> bool:
    return any(h in base_url for h in _OPENAI_CLOUD_HOSTS)


def _is_thinking_model(model_name: str) -> bool:
    """Return True if the model is a chain-of-thought reasoning model."""
    name = model_name.lower()
    return any(name.startswith(p) or f"/{p}" in name for p in _THINKING_MODEL_PREFIXES)


def _build_compact_context(context: InvestigationContext) -> str:
    """
    Build a compact representation of InvestigationContext for local models.
    - Strips raw_payload blobs entirely
    - Caps at 8 most recent evidence items (keeps prompt under ~2K tokens)
    - Truncates long observation strings to 200 chars
    """
    data = context.model_dump()
    evidence = data.get("evidence_items", [])
    # Keep the most recent 8 items
    evidence = evidence[-8:]
    for item in evidence:
        item.pop("raw_payload", None)
        if isinstance(item.get("observation"), str) and len(item["observation"]) > 200:
            item["observation"] = item["observation"][:200] + "…"
    data["evidence_items"] = evidence
    # Only keep keys the LLM needs
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

    Handles three distinct backends transparently:
      - Cloud OpenAI (api.openai.com): full context, response_format=json_object
      - Local Ollama standard models (llama, mistral, granite…): compact context, schema in prompt
      - Local Ollama thinking models (qwen3, qwq, deepseek-r1…): same as above + /no_think
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY or "local"
        self.base_url = (base_url or settings.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        self.model_name = model_name or settings.LLM_MODEL or "gpt-4o-mini"
        self._is_cloud = _is_cloud_openai(self.base_url)
        self._is_thinking = not self._is_cloud and _is_thinking_model(self.model_name)

    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        start_time = time.time()

        if self._is_cloud:
            # Cloud OpenAI: full context JSON, structured output via response_format
            context_body = context.model_dump_json(indent=2)
            user_content = f"Analyze the following InvestigationContext and generate an RCA JSON:\n\n{context_body}"
        else:
            # Local LLMs: compact context + schema injected in prompt
            context_body = _build_compact_context(context)
            user_content = (
                f"Analyze the InvestigationContext below and return an RCA.\n\n"
                f"{_RCA_JSON_SCHEMA}\n"
                f"InvestigationContext:\n{context_body}"
            )
            if self._is_thinking:
                # /no_think disables chain-of-thought for Qwen3/QwQ/DeepSeek-R1
                # This prevents the model from spending minutes on internal reasoning
                # before producing the JSON output.
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

        # Only send response_format for cloud OpenAI
        if self._is_cloud:
            payload["response_format"] = {"type": "json_object"}

        # For Ollama: pass think=false via options for thinking models
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
            if not res.ok:
                logger.error(f"Ollama/OpenAI API returned HTTP {res.status_code}: {res.text[:500]}")
                res.raise_for_status()
            data = res.json()
            raw_text = data["choices"][0]["message"]["content"]
            # Strip any residual <think>...</think> block before parsing
            if "<think>" in raw_text and "</think>" in raw_text:
                raw_text = raw_text[raw_text.rfind("</think>") + len("</think>"):].strip()
            rca = self._validate_and_parse_rca(raw_text, context.investigation_id)

            metadata = {
                "provider": "openai" if self._is_cloud else "ollama",
                "model": self.model_name,
                "latency_seconds": round(time.time() - start_time, 3),
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens"),
                "completion_tokens": data.get("usage", {}).get("completion_tokens"),
            }
            return rca, metadata
        except Exception as e:
            logger.error(f"OpenAI generation failed: {str(e)}")
            raise
