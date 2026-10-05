"""Input validation helpers."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class StartCrawlForm(BaseModel):
    seed_url: str = Field(..., min_length=4, max_length=2048)
    max_urls: int = Field(default=100, ge=1, le=10000)
    rate_per_sec: float = Field(default=2.0, ge=0.1, le=50.0)
    permission_ack: bool = False

    @field_validator("seed_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https?://", v, re.I):
            raise ValueError("URL must start with http:// or https://")
        parsed = urlparse(v)
        if not parsed.netloc:
            raise ValueError("URL must include a host name")
        if parsed.username or parsed.password:
            raise ValueError("URLs with embedded credentials are not allowed")
        return v

    @field_validator("permission_ack")
    @classmethod
    def validate_permission(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must confirm site ownership or permission to crawl")
        return v
