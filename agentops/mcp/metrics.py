import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MCPToolMetric(BaseModel):
    tool_name: str
    duration_seconds: float
    success: bool
    error_message: Optional[str] = None


class MCPMetricsTracker:
    """
    In-memory metrics tracker for MCP tool calls and connections.
    """

    def __init__(self):
        self.request_count: int = 0
        self.tool_invocation_count: int = 0
        self.tool_failures: int = 0
        self.connection_failures: int = 0
        self.timeout_count: int = 0
        self.invocations: List[MCPToolMetric] = []

    def record_call(self, tool_name: str, duration: float, success: bool, error: Optional[str] = None):
        self.request_count += 1
        self.tool_invocation_count += 1
        if not success:
            self.tool_failures += 1
            if error and "timeout" in error.lower():
                self.timeout_count += 1

        self.invocations.append(
            MCPToolMetric(
                tool_name=tool_name,
                duration_seconds=round(duration, 4),
                success=success,
                error_message=error,
            )
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "total_requests": self.request_count,
            "tool_invocations": self.tool_invocation_count,
            "tool_failures": self.tool_failures,
            "connection_failures": self.connection_failures,
            "timeout_count": self.timeout_count,
            "recent_invocations": [m.model_dump() for m in self.invocations[-10:]],
        }

    def to_dict(self) -> Dict[str, Any]:
        return self.summary()
