"""Request/response models of the identity API. They mirror contracts/openapi/identity.yaml.

JSON is camelCase on the wire (`displayName`); Python stays snake_case. Kept apart from domain/ types so
the wire format can change without touching business rules.
Passwords: validation errors never echo the submitted value (see common.problems: field + code only).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from identity_service.domain.models import IssuedTokens, SignUp, User


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SignUpIn(_Wire):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)

    def to_cmd(self) -> SignUp:
        return SignUp(str(self.email), self.password, self.display_name, self.timezone)


class SignInIn(_Wire):
    # Deliberately loose: a malformed email or an over-long password must look exactly like a wrong
    # password (401), not like a validation error that tells an attacker something. Only size is capped,
    # so nobody can make us hash megabytes.
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class TokensOut(_Wire):
    access_token: str
    expires_in: int  # seconds

    @classmethod
    def from_issued(cls, issued: IssuedTokens) -> TokensOut:
        return cls(access_token=issued.access_token, expires_in=issued.expires_in)


class UserOut(_Wire):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    email: str
    email_verified: bool
    display_name: str
    initials: str
    color: str
    avatar_url: str | None
    timezone: str | None
    locale: str | None

    @classmethod
    def from_domain(cls, user: User) -> UserOut:
        return cls(**{name: getattr(user, name) for name in cls.model_fields})
