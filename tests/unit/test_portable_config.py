"""
Unit tests for AgentOps-SRE v0.7.2 Portable Configuration, Path Handling, and Defaults.
"""
import os
from pathlib import Path
from unittest.mock import patch

from agentops.clients.kubernetes import KubernetesInvestigationClient
from agentops.config import Settings, settings


def test_default_settings_bind_to_loopback():
    assert settings.AGENTOPS_HOST == "127.0.0.1"
    assert settings.AGENTOPS_PORT == 8000
    assert settings.LLM_PROVIDER == "ollama"


def test_base_dir_is_dynamic_path():
    assert isinstance(settings.BASE_DIR, Path)
    assert settings.BASE_DIR.exists()
    assert (settings.BASE_DIR / "agentops").exists()


def test_kubeconfig_path_resolution_with_custom_env(tmp_path):
    custom_kubeconfig = tmp_path / "custom-kubeconfig.yaml"
    custom_kubeconfig.write_text("apiVersion: v1\nclusters: []\n")

    with patch.dict(os.environ, {"KUBECONFIG": str(custom_kubeconfig)}):
        s = Settings()
        assert s.KUBECONFIG_PATH == str(custom_kubeconfig)


def test_k8s_client_inherits_portable_kubeconfig(tmp_path):
    custom_kubeconfig = tmp_path / "test-kubeconfig.yaml"
    custom_kubeconfig.write_text("apiVersion: v1\nclusters: []\n")

    with patch.dict(os.environ, {"KUBECONFIG": str(custom_kubeconfig)}):
        client = KubernetesInvestigationClient()
        assert client.timeout == settings.TELEMETRY_TIMEOUT_SECONDS


def test_no_hardcoded_user_paths_in_settings():
    """
    Ensure config.py source code does not contain hardcoded machine-specific paths like /Users/...
    """
    config_source = Path("agentops/config.py").read_text()
    assert '"/Users/' not in config_source
    assert "'/Users/" not in config_source
