import json
import logging
import time
from typing import Any, Dict, Tuple
import requests
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider, RCA_SYSTEM_PROMPT
from agentops.models.evidence import InvestigationContext
from agentops.models.rca import RootCauseAnalysis

logger = logging.getLogger("agentops.llm.openai")


class OpenAILLMProvider(BaseLLMProvider):
    """
    OpenAI / Ollama-compatible LLM Provider.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", model_name: str = "gpt-4o-mini"):
        self.api_key = api_key or "local"
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name or "gpt-4o-mini"

    def generate_rca(self, context: InvestigationContext) -> Tuple[RootCauseAnalysis, Dict[str, Any]]:
        start_time = time.time()
        context_json = context.model_dump_json(indent=2)
        user_prompt = f"Analyze the following InvestigationContext and generate an RCA JSON:\n\n{context_json}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": RCA_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        try:
            res = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=30)
            res.raise_for_status()
            data = res.json()
            raw_text = data["choices"][0]["message"]["content"]
            rca = self._validate_and_parse_rca(raw_text, context.investigation_id)

            metadata = {
                "provider": "openai",
                "model": self.model_name,
                "latency_seconds": round(time.time() - start_time, 3),
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens"),
                "completion_tokens": data.get("usage", {}).get("completion_tokens"),
            }
            return rca, metadata
        except Exception as e:
            logger.error(f"OpenAI generation failed: {str(e)}")
            raise
