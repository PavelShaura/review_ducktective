import asyncio
from dataclasses import (
    dataclass,
)
from typing import (
    Any,
)

import httpx

from ducktective.core.exceptions import (
    NotAuthenticatedError,
)


DISCOVERY_PATH = "/.well-known/openid-configuration"
DEFAULT_SCOPE = "openid email profile"
SLOW_DOWN_STEP_SECONDS = 5


@dataclass(frozen=True, kw_only=True)
class DeviceAuthorization:
    """Что показать человеку, чтобы он подтвердил вход в браузере."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    interval_seconds: int
    expires_in_seconds: int


@dataclass(frozen=True, kw_only=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in_seconds: int


class DeviceFlowClient:
    """Вход из терминала: у него нет браузера и негде хранить секрет клиента.

    Поэтому клиент публичный, а подтверждение человек даёт в браузере —
    на другом устройстве, если нужно. Терминал в это время опрашивает
    провайдера и ждёт.
    """

    def __init__(self, *, issuer: str, client_id: str, client: httpx.AsyncClient) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._http = client
        self._endpoints: dict[str, str] = {}

    async def start(self) -> DeviceAuthorization:
        endpoint = await self._endpoint("device_authorization_endpoint")
        payload = await self._post(
            endpoint,
            {"client_id": self._client_id, "scope": DEFAULT_SCOPE},
        )
        return DeviceAuthorization(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            verification_uri_complete=(
                str(payload["verification_uri_complete"])
                if "verification_uri_complete" in payload
                else None
            ),
            interval_seconds=int(payload.get("interval", 5)),
            expires_in_seconds=int(payload.get("expires_in", 600)),
        )

    async def wait_for_token(self, authorization: DeviceAuthorization) -> TokenPair:
        """Опрашивает провайдера, пока человек подтверждает вход.

        Интервал опроса называет провайдер и вправе его увеличить: ответ
        `slow_down` — не ошибка, а просьба спрашивать реже, и не послушаться
        значит получить отказ.
        """
        endpoint = await self._endpoint("token_endpoint")
        interval = authorization.interval_seconds
        deadline = asyncio.get_running_loop().time() + authorization.expires_in_seconds

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(interval)
            payload = await self._post(
                endpoint,
                {
                    "client_id": self._client_id,
                    "device_code": authorization.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                allow_error=True,
            )
            error = payload.get("error")
            if error is None:
                return _to_pair(payload)
            if error == "slow_down":
                interval += SLOW_DOWN_STEP_SECONDS
                continue
            if error == "authorization_pending":
                continue
            raise NotAuthenticatedError(f"Вход не подтверждён: {error}")

        raise NotAuthenticatedError("Время на подтверждение входа истекло")

    async def refresh(self, refresh_token: str) -> TokenPair:
        endpoint = await self._endpoint("token_endpoint")
        payload = await self._post(
            endpoint,
            {
                "client_id": self._client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            allow_error=True,
        )
        if "error" in payload:
            raise NotAuthenticatedError("Сохранённый вход больше не действует, войдите заново")
        return _to_pair(payload)

    async def _endpoint(self, name: str) -> str:
        if not self._endpoints:
            document = await self._get(self._issuer + DISCOVERY_PATH)
            self._endpoints = {
                key: str(value) for key, value in document.items() if isinstance(value, str)
            }

        endpoint = self._endpoints.get(name)
        if endpoint is None:
            raise NotAuthenticatedError(f"Провайдер личности не поддерживает {name}")
        return endpoint

    async def _get(self, url: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
        except httpx.HTTPError as error:
            raise NotAuthenticatedError("Провайдер личности недоступен") from error
        return document

    async def _post(
        self,
        url: str,
        data: dict[str, str],
        *,
        allow_error: bool = False,
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(url, data=data)
            if not allow_error:
                response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except httpx.HTTPError as error:
            raise NotAuthenticatedError("Провайдер личности недоступен") from error
        except ValueError as error:
            raise NotAuthenticatedError("Провайдер личности ответил не по протоколу") from error
        return payload


def _to_pair(payload: dict[str, Any]) -> TokenPair:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise NotAuthenticatedError("Провайдер личности не выдал токены")
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=int(payload.get("expires_in", 300)),
    )
