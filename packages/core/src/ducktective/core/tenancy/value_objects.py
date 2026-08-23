import hashlib
import secrets
from dataclasses import (
    dataclass,
)
from enum import (
    StrEnum,
)
from typing import (
    Self,
)


class TenantRole(StrEnum):
    """Роль участника в организации.

    Ролей две, потому что различаются они одним: состав организации и политика
    egress репозитория меняются владельцем. Всё остальное — заведение
    репозиториев, прогоны, разговоры, отметки — доступно любому участнику,
    и дробить это дальше значит заводить права, которых никто не спрашивал.
    """

    OWNER = "owner"
    MEMBER = "member"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


@dataclass(frozen=True)
class InvitationToken:
    """Секрет из ссылки-приглашения.

    В базе лежит только отпечаток: приглашение — способ войти в чужую
    организацию, и хранить его в пригодном к предъявлению виде значит
    держать в таблице готовый ключ.
    """

    value: str

    @classmethod
    def issue(cls) -> Self:
        return cls(secrets.token_urlsafe(32))

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()

    def matches(self, digest: str) -> bool:
        return secrets.compare_digest(self.digest, digest)


@dataclass(frozen=True, kw_only=True)
class VerifiedIdentity:
    """Личность, подтверждённая внешним провайдером.

    Пара «издатель и субъект» опознаёт человека, а не почта: почту в Keycloak
    меняют, и привязка по ней отдала бы чужую учётную запись тому, кто занял
    освободившийся адрес.
    """

    issuer: str
    subject: str
    email: str
