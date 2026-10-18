"""
Unit tests for AgentOps-SRE v0.7.2 Real AI Enforcement, Typed Error Taxonomy,
Evidence Validation, and Fail-Closed Approval Invariants.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from agentops.incident.orchestrator import IncidentOrchestrator
from agentops.llm.exceptions import (
    EvidenceValidationError,
    InferenceTimeoutError,
    InvalidModelOutputError,
    ModelNotFoundError,
    ProviderUnavailableError,
)
from agentops.llm.openai_provider import OpenAILLMProvider
from agentops.models.evidence import (
    InvestigationContext,
    TelemetrySource,
)
from agentops.models.rca import IncidentType


def test_typed_error_taxonomy_serialization():
    err = ModelNotFoundError("Model 'test:latest' not found", provider="ollama", model="test:latest")
    assert err.error_category == "ModelNotFoundError"
    d = err.to_dict()
    assert d["error_category"] == "ModelNotFoundError"
    assert d["provider"] == "ollama"
    assert d["model"] == "test:latest"
    assert "not found" in d["message"]


def test_ollama_model_not_found_raises_model_not_found_error():
    provider = OpenAILLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="nonexistent-model:99b",
    )
    context = InvestigationContext(investigation_id="inv-123", namespace="demo", workload="demo-app")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "qwen3.5:2b"}, {"name": "granite4.1:3b"}]
    }

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(ModelNotFoundError) as exc_info:
            provider.generate_rca(context)
        assert "not found in Ollama inventory" in str(exc_info.value)
        assert exc_info.value.error_category == "ModelNotFoundError"


def test_ollama_connection_refused_raises_provider_unavailable_error():
    provider = OpenAILLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:2b",
    )
    context = InvestigationContext(investigation_id="inv-123", namespace="demo", workload="demo-app")

    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        with pytest.raises(ProviderUnavailableError) as exc_info:
            provider.generate_rca(context)
        assert "Ollama server is unavailable" in str(exc_info.value)
        assert exc_info.value.error_category == "ProviderUnavailableError"


def test_inference_timeout_raises_inference_timeout_error():
    provider = OpenAILLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:2b",
    )
    context = InvestigationContext(investigation_id="inv-123", namespace="demo", workload="demo-app")

    mock_tags = MagicMock()
    mock_tags.status_code = 200
    mock_tags.json.return_value = {"models": [{"name": "qwen3.5:2b"}]}

    with (
        patch("requests.get", return_value=mock_tags),
        patch("requests.post", side_effect=requests.exceptions.Timeout("Read timed out")),
    ):
        with pytest.raises(InferenceTimeoutError) as exc_info:
            provider.generate_rca(context)
        assert "inference timed out" in str(exc_info.value)
        assert exc_info.value.error_category == "InferenceTimeoutError"


def test_invalid_json_output_raises_invalid_model_output_error():
    provider = OpenAILLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:2b",
    )
    context = InvestigationContext(investigation_id="inv-123", namespace="demo", workload="demo-app")

    mock_tags = MagicMock()
    mock_tags.status_code = 200
    mock_tags.json.return_value = {"models": [{"name": "qwen3.5:2b"}]}

    mock_post = MagicMock()
    mock_post.ok = True
    mock_post.json.return_value = {
        "choices": [{"message": {"content": "This is plain text, not valid JSON RCA output."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }

    with (
        patch("requests.get", return_value=mock_tags),
        patch("requests.post", return_value=mock_post),
    ):
        with pytest.raises(InvalidModelOutputError) as exc_info:
            provider.generate_rca(context)
        assert exc_info.value.error_category == "InvalidModelOutputError"


def test_hallucinated_evidence_id_raises_evidence_validation_error():
    provider = OpenAILLMProvider(
        base_url="http://127.0.0.1:11434/v1",
        model_name="qwen3.5:2b",
    )
    context = InvestigationContext(investigation_id="inv-123", namespace="demo", workload="demo-app")
    context.add_evidence(
        source=TelemetrySource.KUBERNETES,
        resource="demo/demo-app",
        metric_or_query="kubectl get pods",
        observation="Pod crash observed",
    )
    # Collected evidence is E001 only.

    mock_tags = MagicMock()
    mock_tags.status_code = 200
    mock_tags.json.return_value = {"models": [{"name": "qwen3.5:2b"}]}

    # Model hallucinates evidence E999
    llm_output_json = """{
      "investigation_id": "inv-123",
      "incident_type": "CrashLoopBackOff",
      "severity": "CRITICAL",
      "summary": "Pod in CrashLoopBackOff",
      "root_cause": "Process exited with code 1",
      "confidence": 0.95,
      "evidence_ids": ["E001", "E999"],
      "timeline": [],
      "recommended_action": "Restart pod",
      "requires_human_approval": true,
      "telemetry_coverage": {"kubernetes": true, "prometheus": false, "loki": false}
    }"""

    mock_post = MagicMock()
    mock_post.ok = True
    mock_post.json.return_value = {
        "choices": [{"message": {"content": llm_output_json}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }

    with (
        patch("requests.get", return_value=mock_tags),
        patch("requests.post", return_value=mock_post),
    ):
        with pytest.raises(EvidenceValidationError) as exc_info:
            provider.generate_rca(context)
        assert "invalid/unsupported evidence references: ['E999']" in str(exc_info.value)
        assert exc_info.value.error_category == "EvidenceValidationError"


def test_failed_inference_never_creates_actionable_approval():
    """
    Security Invariant: When LLM inference fails (e.g. connection error, validation failure),
    IncidentOrchestrator must fail closed:
    - Status is FAILED
    - validation_passed is False
    - approval_required is False
    - approval_id is None
    - No ActionRequest is dispatched
    """
    orchestrator = IncidentOrchestrator()

    mock_provider = MagicMock()
    mock_provider.model_name = "qwen3.5:2b"
    mock_provider.provider_label = "ollama"
    mock_provider.last_metadata = {
        "provider": "ollama",
        "model": "qwen3.5:2b",
        "latency_seconds": 0.1,
    }
    mock_provider.generate_rca.side_effect = ProviderUnavailableError(
        "Ollama unreachable", provider="ollama", model="qwen3.5:2b"
    )

    with patch.object(orchestrator, "_get_provider", return_value=mock_provider):
        report = orchestrator.investigate_and_recommend(
            namespace="demo",
            workload="demo-app",
            provider_name="ollama",
            model_name="qwen3.5:2b",
        )

        assert report.status == "FAILED"
        assert report.approval_required is False
        assert report.approval_id is None
        assert report.recommended_remediation == "No automated remediation permitted due to failed or unvalidated investigation."
        assert report.policy_decision == "NOT_EVALUATED"
        assert report.validation_passed is False


def test_unknown_incident_type_fails_closed_without_action():
    """
    Security Invariant: If RCA produces an Unknown incident type,
    it must fail closed without defaulting to restart or generating an approval.
    """
    orchestrator = IncidentOrchestrator()

    action_name, rec_text, params = orchestrator._map_rca_to_action(
        incident_type=IncidentType.UNKNOWN,
        workload="demo-app",
        namespace="demo",
    )
    assert action_name == "none"
    assert "No automated action authorized" in rec_text
    assert params == {}
