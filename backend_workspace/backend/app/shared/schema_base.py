"""Base Pydantic model for API schemas: strict, trimmed, camelCase on the wire."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Forbids unknown fields (-> 400), strips whitespace, and uses camelCase aliases."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ApiResponseModel(ApiModel):
    """Base for response schemas; serialize with ``by_alias=True`` (FastAPI default)."""
