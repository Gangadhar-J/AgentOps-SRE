from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field
from agentops.security.capabilities import Capability
from agentops.security.identity import AgentIdentity


class SecurityContext(BaseModel):
    """
    Immutable security context combining agent identity, granted capabilities,
    and request metadata. Ready to be evaluated by future Policy Gateways.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: AgentIdentity = Field(
        ...,
        description="Authenticated agent identity",
    )
    capabilities: Tuple[Capability, ...] = Field(
        default_factory=tuple,
        description="Tuple of granted capability permissions",
    )
    request_id: str = Field(
        ...,
        pattern=r"^req-[a-zA-Z0-9_-]+$",
        description="Correlation request identifier",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional request or environmental context metadata",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC creation timestamp",
    )

    def has_capability_name(self, capability_name: str) -> bool:
        """
        Check if context contains a specific capability name.
        """
        return any(c.name == capability_name for c in self.capabilities)

    def get_matching_capabilities(self, domain: str, operation: str) -> List[Capability]:
        """
        Query granted capabilities matching a domain and operation.
        """
        prefix = f"{domain}.{operation}."
        return [c for c in self.capabilities if c.name.startswith(prefix)]
