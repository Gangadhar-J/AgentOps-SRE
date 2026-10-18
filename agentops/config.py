import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR: Path = Path(__file__).resolve().parent.parent


class Settings:
    # Server Binding (defaults strictly to localhost 127.0.0.1 for development security)
    AGENTOPS_HOST: str = os.getenv("AGENTOPS_HOST", "127.0.0.1")
    AGENTOPS_PORT: int = int(os.getenv("AGENTOPS_PORT", "8000"))

    # Telemetry Endpoints
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://localhost:30090")
    LOKI_URL: str = os.getenv("LOKI_URL", "http://localhost:31000")
    GRAFANA_URL: str = os.getenv("GRAFANA_URL", "http://localhost:30300")

    # Kubernetes Configuration
    # Portably checks KUBECONFIG env var first, then ~/.kube/config
    KUBECONFIG_PATH: str = os.getenv(
        "KUBECONFIG",
        os.getenv("KUBECONFIG_PATH", str(Path.home() / ".kube" / "config")),
    )
    DEFAULT_NAMESPACE: str = os.getenv("DEMO_NAMESPACE", "demo")

    # LLM Provider Configuration
    # Default is real local provider 'ollama'; mock is prohibited in live paths
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen3.5:2b")

    # Investigation Limits & Timeouts
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
    TELEMETRY_TIMEOUT_SECONDS: int = int(os.getenv("TELEMETRY_TIMEOUT_SECONDS", "5"))
    LOGS_LIMIT: int = int(os.getenv("LOGS_LIMIT", "50"))
    EVENTS_LIMIT: int = int(os.getenv("EVENTS_LIMIT", "30"))

    # Project Paths (fully portable across developer workstations, CI, and containers)
    BASE_DIR: Path = BASE_DIR
    POLICIES_PATH: str = os.getenv("POLICIES_PATH", str(BASE_DIR / "config" / "policies.yaml"))
    DATA_DIR: Path = Path(os.getenv("AGENTOPS_DATA_DIR", str(BASE_DIR / "data")))
    DB_PATH: str = os.getenv("AGENTOPS_DB_PATH", str(DATA_DIR / "agentops.db"))

    # Logging & Observability
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper().strip()
    OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower().strip() in ("1", "true", "yes")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    def __init__(self):
        self.AGENTOPS_HOST = os.getenv("AGENTOPS_HOST", "127.0.0.1")
        self.AGENTOPS_PORT = int(os.getenv("AGENTOPS_PORT", "8000"))
        self.PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:30090")
        self.LOKI_URL = os.getenv("LOKI_URL", "http://localhost:31000")
        self.GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:30300")
        self.KUBECONFIG_PATH = os.getenv(
            "KUBECONFIG",
            os.getenv("KUBECONFIG_PATH", str(Path.home() / ".kube" / "config")),
        )
        self.DEFAULT_NAMESPACE = os.getenv("DEMO_NAMESPACE", "demo")
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower().strip()
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5:2b")
        self.LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
        self.TELEMETRY_TIMEOUT_SECONDS = int(os.getenv("TELEMETRY_TIMEOUT_SECONDS", "5"))
        self.LOGS_LIMIT = int(os.getenv("LOGS_LIMIT", "50"))
        self.EVENTS_LIMIT = int(os.getenv("EVENTS_LIMIT", "30"))
        self.BASE_DIR = BASE_DIR
        self.POLICIES_PATH = os.getenv("POLICIES_PATH", str(BASE_DIR / "config" / "policies.yaml"))
        self.DATA_DIR = Path(os.getenv("AGENTOPS_DATA_DIR", str(BASE_DIR / "data")))
        self.DB_PATH = os.getenv("AGENTOPS_DB_PATH", str(self.DATA_DIR / "agentops.db"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper().strip()
        self.OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower().strip() in ("1", "true", "yes")
        self.OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    def ensure_directories(self) -> None:
        """Create runtime data directories with appropriate permissions."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
