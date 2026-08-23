from collections.abc import (
    Callable,
)
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from pathlib import (
    Path,
)

import httpx

from ducktective.auth.credentials import (
    DEFAULT_LOCATION,
    StoredCredentials,
    forget_credentials,
    load_credentials,
    save_credentials,
)
from ducktective.auth.device_flow import (
    DeviceAuthorization,
    DeviceFlowClient,
    TokenPair,
)
from ducktective.core.exceptions import (
    NotAuthenticatedError,
)


class TerminalSession:
    """Вход терминала: подтверждение в браузере, дальше — сохранённый токен.

    Команда, требующая базы, не должна каждый раз звать браузер, поэтому
    рядом с токеном доступа лежит обновляющий. Просроченный обновляется
    молча; переставший действовать — повод войти заново, и сказать об этом
    надо прямо, а не отказом в доступе посреди работы.
    """

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        location: Path = DEFAULT_LOCATION,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._location = location

    async def login(self, announce: Callable[[DeviceAuthorization], None]) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            flow = self._flow(client)
            authorization = await flow.start()
            announce(authorization)
            tokens = await flow.wait_for_token(authorization)

        save_credentials(self._store(tokens), self._location)

    async def access_token(self) -> str:
        credentials = load_credentials(self._location)
        if credentials is None:
            raise NotAuthenticatedError(
                "Вход не выполнен: `ducktective login` или режим `--no-store`"
            )
        if credentials.issuer != self._issuer:
            raise NotAuthenticatedError("Сохранённый вход относится к другому провайдеру личности")
        if credentials.is_fresh():
            return credentials.access_token

        async with httpx.AsyncClient(timeout=30.0) as client:
            tokens = await self._flow(client).refresh(credentials.refresh_token)

        refreshed = self._store(tokens)
        save_credentials(refreshed, self._location)
        return refreshed.access_token

    def logout(self) -> bool:
        return forget_credentials(self._location)

    def _flow(self, client: httpx.AsyncClient) -> DeviceFlowClient:
        return DeviceFlowClient(
            issuer=self._issuer,
            client_id=self._client_id,
            client=client,
        )

    def _store(self, tokens: TokenPair) -> StoredCredentials:
        return StoredCredentials(
            issuer=self._issuer,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=tokens.expires_in_seconds),
        )
