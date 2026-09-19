import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import requests
from agentops.config import settings
from agentops.llm.base import BaseLLMProvider, RCA_SYSTEM_PROMPT
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
            raise ValueError(
                "GEMINI_API_KEY is not configured. Please export GEMINI_API_KEY=<your-key> or set it in your .env file."
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
        # Support both Google AI Studio API keys (AIza...) and OAuth Bearer tokens (AQ..., ya29...)
        if self.api_key.startswith("AQ.") or self.api_key.startswith("ya29."):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers["x-goog-api-key"] = self.api_key

        try:
            res = requests.post(self.endpoint, headers=headers, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
            if not res.ok:
                logger.error(f"Gemini API returned HTTP {res.status_code}: {res.text}")
                res.raise_for_status()
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            rca = self._validate_and_parse_rca(raw_text, context.investigation_id)

            metadata = {
                "provider": "gemini",
                "model": self.model_name,
                "latency_seconds": round(time.time() - start_time, 3),
                "prompt_tokens": data.get("usageMetadata", {}).get("promptTokenCount"),
                "completion_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount"),
            }
            return rca, metadata
        except Exception as e:
            logger.error(f"Gemini generation failed: {str(e)}")
            raise
