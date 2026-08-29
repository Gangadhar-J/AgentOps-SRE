import json
import logging
import time
from typing import Any, Dict, List, Optional
import requests
from agentops.config import settings

logger = logging.getLogger("agentops.loki")


class LokiClient:
    """
    Read-only HTTP client for querying logs from Grafana Loki.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.base_url = (base_url or settings.LOKI_URL).rstrip("/")
        self.timeout = timeout or settings.TELEMETRY_TIMEOUT_SECONDS

    def is_available(self) -> bool:
        try:
            res = requests.get(f"{self.base_url}/ready", timeout=self.timeout)
            return res.status_code == 200 and "ready" in res.text.lower()
        except Exception:
            return False

    def query_range(
        self,
        logql: str,
        limit: int = 50,
        start_ns: Optional[int] = None,
        end_ns: Optional[int] = None,
        lookback_seconds: int = 180,
    ) -> List[Dict[str, Any]]:
        """
        Execute a LogQL query (/loki/api/v1/query_range).
        Defaults to searching recent lookback window.
        """
        now_ns = int(time.time() * 1e9)
        start = start_ns or (now_ns - int(lookback_seconds * 1e9))
        end = end_ns or now_ns

        params: Dict[str, Any] = {
            "query": logql,
            "limit": limit,
            "direction": "BACKWARD",
            "start": str(start),
            "end": str(end),
        }

        try:
            res = requests.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params=params,
                timeout=self.timeout,
            )
            res.raise_for_status()
            data = res.json()
            if data.get("status") != "success":
                return []

            parsed_logs: List[Dict[str, Any]] = []
            for stream in data.get("data", {}).get("result", []):
                stream_labels = stream.get("stream", {})
                for entry in stream.get("values", []):
                    ts_ns, raw_line = entry[0], entry[1]
                    log_item: Dict[str, Any] = {
                        "timestamp_ns": ts_ns,
                        "labels": stream_labels,
                        "raw": raw_line,
                    }
                    try:
                        parsed_json = json.loads(raw_line.strip())
                        log_item["json"] = parsed_json
                        log_item["level"] = parsed_json.get("level")
                        log_item["message"] = parsed_json.get("message")
                        log_item["error_type"] = parsed_json.get("error_type")
                        log_item["request_id"] = parsed_json.get("request_id")
                        log_item["stack_trace"] = parsed_json.get("stack_trace")
                    except Exception:
                        log_item["level"] = "UNKNOWN"
                        log_item["message"] = raw_line.strip()
                    parsed_logs.append(log_item)

            return parsed_logs
        except Exception as e:
            logger.error(f"Loki query failed for '{logql}': {str(e)}")
            raise

    def get_error_logs(
        self, namespace: str, app: str, limit: int = 20, lookback_seconds: int = 180
    ) -> List[Dict[str, Any]]:
        query = f'{{namespace="{namespace}", app="{app}"}} | json | level="ERROR" or level="CRITICAL"'
        try:
            logs = self.query_range(query, limit=limit, lookback_seconds=lookback_seconds)
            if not logs:
                fallback_query = f'{{namespace="{namespace}", app="{app}"}} |= "ERROR"'
                logs = self.query_range(fallback_query, limit=limit, lookback_seconds=lookback_seconds)
            return logs
        except Exception:
            return []

    def get_fatal_crash_logs(
        self, namespace: str, app: str, limit: int = 10, lookback_seconds: int = 180
    ) -> List[Dict[str, Any]]:
        query = f'{{namespace="{namespace}", app="{app}"}} |= "FATAL"'
        try:
            return self.query_range(query, limit=limit, lookback_seconds=lookback_seconds)
        except Exception:
            return []

    def get_memory_leak_logs(
        self, namespace: str, app: str, limit: int = 10, lookback_seconds: int = 180
    ) -> List[Dict[str, Any]]:
        query = f'{{namespace="{namespace}", app="{app}"}} |= "Memory allocation leak"'
        try:
            return self.query_range(query, limit=limit, lookback_seconds=lookback_seconds)
        except Exception:
            return []

    def get_logs_by_request_id(
        self, request_id: str, namespace: str = "demo", lookback_minutes: int = 10, limit: int = 20
    ) -> List[Dict[str, Any]]:
        query = f'{{namespace="{namespace}"}} |= "{request_id}"'
        try:
            return self.query_range(query, limit=limit, lookback_seconds=lookback_minutes * 60)
        except Exception:
            return []
