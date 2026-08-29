from datetime import datetime, timezone
import re
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from agentops.security.identity import SECRET_PATTERNS


class OperatorIdentity(BaseModel):
    """
    Immutable identity representing a human operator or authorized admin.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="Unique operator username or identifier (e.g. 'alice.sre')",
    )
    operator_type: Literal["human_operator", "admin"] = Field(
        default="human_operator",
        description="Operator classification",
    )
    display_name: str = Field(
        ...,
        min_length=2,
        max_length=128,
        description="Full display name (e.g. 'Alice Engineer')",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp",
    )

    @field_validator("operator_id", "display_name")
    @classmethod
    def validate_no_secrets(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Field cannot be empty or whitespace only")
        for pattern in SECRET_PATTERNS:
            if pattern.search(trimmed):
                raise ValueError("OperatorIdentity must not contain secret tokens or passwords")
        return trimmed
