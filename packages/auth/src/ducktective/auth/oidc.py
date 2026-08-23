import time
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
)

import httpx
import jwt
from jwt import (
    PyJWK,
)

from ducktective.core.exceptions import (
    NotAuthenticatedError,
)
from ducktective.core.tenancy.value_objects import (
    VerifiedIdentity,
)


DISCOVERY_PATH = "/.well-known/openid-configuration"
SUPPORTED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384")


@dataclass(frozen=True, kw_only=True)
class OidcSettings:
    """Куда ходить за ключами и чей токен считать своим.

    `audience` пустой отключает проверку получателя. Это осознанная поблажка
    сборкам, где токену не настроен маппер аудитории: Keycloak по умолчанию
    кладёт в `aud` служебное значение, и жёсткая проверка отвергала бы все
    токены до правки realm. В поставляемом realm аудитория настроена,
    и значение здесь задано.
    """

    issuer: str
    audience: str = ""
    jwks_uri: str = ""
    leeway_seconds: int = 30
    keys_ttl_seconds: int = 600
    refresh_cooldown_seconds: int = 30


@dataclass
class _KeyCache:
    keys: dict[str, PyJWK] = field(default_factory=dict)
    fetched_at: float = 0.0
    last_attempt_at: float = 0.0


class OidcIdentityVerifier:
    """Проверка токена доступа подписью провайдера личности.

    Ключи кэшируются: их запрос на каждый обращение к API превратил бы
    провайдера в участника каждого запроса. Незнакомый `kid` кэш обновляет —
    ротация ключей иначе выглядела бы как массовый отказ в доступе, — но не
    чаще, чем раз в `refresh_cooldown_seconds`: иначе поток токенов с чужой
    подписью превращается в поток запросов к провайдеру.
    """

    def __init__(self, settings: OidcSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self._cache = _KeyCache()
        self._jwks_uri = settings.jwks_uri

    async def verify(self, token: str) -> VerifiedIdentity:
        if not token.strip():
            raise NotAuthenticatedError("Токен не предъявлен")

        key = await self._resolve_key(token)
        claims = self._decode(token, key)
        return self._to_identity(claims)

    async def _resolve_key(self, token: str) -> PyJWK:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise NotAuthenticatedError("Токен не разбирается") from error

        key_id = header.get("kid")
        if not isinstance(key_id, str):
            raise NotAuthenticatedError("В заголовке токена нет идентификатора ключа")

        cached = await self._keys()
        if key_id in cached:
            return cached[key_id]

        refreshed = await self._keys(force=True)
        if key_id not in refreshed:
            raise NotAuthenticatedError("Токен подписан неизвестным ключом")
        return refreshed[key_id]

    def _decode(self, token: str, key: PyJWK) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=list(SUPPORTED_ALGORITHMS),
                issuer=self._settings.issuer,
                audience=self._settings.audience or None,
                leeway=self._settings.leeway_seconds,
                options={
                    "require": ["exp", "iss", "sub"],
                    "verify_aud": bool(self._settings.audience),
                },
            )
        except jwt.ExpiredSignatureError as error:
            raise NotAuthenticatedError("Срок действия токена истёк") from error
        except jwt.PyJWTError as error:
            raise NotAuthenticatedError("Токен не прошёл проверку") from error
        return claims

    @staticmethod
    def _to_identity(claims: dict[str, Any]) -> VerifiedIdentity:
        subject = claims.get("sub")
        issuer = claims.get("iss")
        email = claims.get("email")
        if not isinstance(subject, str) or not isinstance(issuer, str):
            raise NotAuthenticatedError("В токене нет субъекта или издателя")
        if not isinstance(email, str) or "@" not in email:
            raise NotAuthenticatedError(
                "В токене нет почтового адреса: приглашения выписываются на него"
            )
        return VerifiedIdentity(issuer=issuer, subject=subject, email=email)

    async def _keys(self, *, force: bool = False) -> dict[str, PyJWK]:
        now = time.monotonic()
        is_fresh = (
            self._cache.keys and now - self._cache.fetched_at < self._settings.keys_ttl_seconds
        )
        if is_fresh and not force:
            return self._cache.keys
        if force and now - self._cache.last_attempt_at < self._settings.refresh_cooldown_seconds:
            return self._cache.keys

        self._cache.last_attempt_at = now
        document = await self._fetch_jwks()
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            try:
                jwk = PyJWK(entry)
            except jwt.PyJWTError:
                continue
            key_id = entry.get("kid")
            if isinstance(key_id, str):
                keys[key_id] = jwk

        if not keys:
            raise NotAuthenticatedError("Провайдер личности не отдал ни одного ключа")

        self._cache.keys = keys
        self._cache.fetched_at = now
        return keys

    async def _fetch_jwks(self) -> dict[str, Any]:
        uri = await self._resolve_jwks_uri()
        try:
            response = await self._client.get(uri)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
        except httpx.HTTPError as error:
            raise NotAuthenticatedError("Провайдер личности недоступен") from error
        return document

    async def _resolve_jwks_uri(self) -> str:
        if self._jwks_uri:
            return self._jwks_uri

        discovery_url = self._settings.issuer.rstrip("/") + DISCOVERY_PATH
        try:
            response = await self._client.get(discovery_url)
            response.raise_for_status()
            document = response.json()
        except httpx.HTTPError as error:
            raise NotAuthenticatedError("Провайдер личности недоступен") from error

        uri = document.get("jwks_uri")
        if not isinstance(uri, str):
            raise NotAuthenticatedError("Провайдер личности не сообщил адрес ключей")

        self._jwks_uri = uri
        return uri
