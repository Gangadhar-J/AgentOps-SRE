import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

class Settings:
    # Telemetry Endpoints
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://localhost:30090")
    LOKI_URL: str = os.getenv("LOKI_URL", "http://localhost:31000")
    GRAFANA_URL: str = os.getenv("GRAFANA_URL", "http://localhost:30300")
    
    # Kubernetes
    KUBECONFIG_PATH: str = os.getenv("KUBECONFIG_PATH", str(Path.home() / ".kube" / "config"))
    DEFAULT_NAMESPACE: str = os.getenv("DEMO_NAMESPACE", "demo")
    
    # LLM Provider Configuration
    # Options: 'auto', 'gemini', 'openai', 'ollama', 'mock'
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto").lower().strip()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "")
    
    # Investigation Limits & Timeouts
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
    TELEMETRY_TIMEOUT_SECONDS: int = int(os.getenv("TELEMETRY_TIMEOUT_SECONDS", "5"))
    LOGS_LIMIT: int = int(os.getenv("LOGS_LIMIT", "50"))
    EVENTS_LIMIT: int = int(os.getenv("EVENTS_LIMIT", "30"))

    # Project Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    POLICIES_PATH: str = os.getenv("POLICIES_PATH", str(BASE_DIR / "config" / "policies.yaml"))
    DB_PATH: str = os.getenv("AGENTOPS_DB_PATH", str(BASE_DIR / "data" / "agentops.db"))

    # Logging & Observability
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower().strip() in ("1", "true", "yes")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

settings = Settings()

