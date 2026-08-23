import asyncio
from contextlib import (
    suppress,
)
from typing import (
    Annotated,
)

from fastapi import (
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
    UnitOfWorkDependency,
)
from ducktective.application.tenancy.sign_in import (
    ResolveSignedInUser,
    SignedInUser,
)
from ducktective.core.exceptions import (
    NotAuthenticatedError,
)
from ducktective.core.tenancy.entities import (
    UserAccount,
)
from ducktective.core.tenancy.ports import (
    IdentityVerifier,
)
from ducktective.core.tenancy.value_objects import (
    VerifiedIdentity,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


bearer_scheme = HTTPBearer(auto_error=False)

NO_ORGANIZATION_DETAIL = (
    "Учётная запись не состоит в организации: создайте свою или примите приглашение"
)


def get_identity_verifier(request: Request) -> IdentityVerifier:
    verifier: IdentityVerifier | None = getattr(request.app.state, "identity_verifier", None)
    if verifier is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Провайдер личности не настроен",
        )
    return verifier


async def authenticated_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[IdentityVerifier, Depends(get_identity_verifier)],
) -> VerifiedIdentity:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Требуется вход",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return await verifier.verify(credentials.credentials)
    except NotAuthenticatedError as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


async def signed_in_user(
    identity: Annotated[VerifiedIdentity, Depends(authenticated_identity)],
    unit_of_work: UnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> SignedInUser:
    """Кто вошёл, вместе с членством, если оно есть.

    Отсутствие членства не ошибка: этим состоянием пользуются ручки создания
    организации и принятия приглашения — им как раз нужен тот, кто ещё нигде
    не состоит.
    """
    use_case = ResolveSignedInUser(unit_of_work, event_publisher)
    return await use_case.execute(identity)


async def current_member(user: Annotated[SignedInUser, Depends(signed_in_user)]) -> UserAccount:
    """Участник организации, от имени которого идёт запрос.

    Тенант берётся отсюда и только отсюда: пока он приходил параметром
    запроса, изоляции не было — чужой идентификатор открывал чужие дела
    вместе с содержимым кода.
    """
    if user.account is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ORGANIZATION_DETAIL)
    return user.account


async def current_owner(
    member: Annotated[UserAccount, Depends(current_member)],
) -> UserAccount:
    if not member.is_owner:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Операция доступна только владельцу организации",
        )
    return member


def tenant_unit_of_work(
    request: Request,
    member: Annotated[UserAccount, Depends(current_member)],
) -> SqlAlchemyUnitOfWork:
    """Единица работы, открытая от имени организации вошедшего.

    Тенант попадает в транзакцию отсюда: политики базы читают его из
    настройки, и запрос, не назвавший тенанта, не увидит ни строки.
    """
    return SqlAlchemyUnitOfWork(
        request.app.state.session_factory,
        tenant_id=member.tenant_id,
    )


TenantUnitOfWorkDependency = Annotated[SqlAlchemyUnitOfWork, Depends(tenant_unit_of_work)]
IdentityDependency = Annotated[VerifiedIdentity, Depends(authenticated_identity)]
SignedInUserDependency = Annotated[SignedInUser, Depends(signed_in_user)]
MemberDependency = Annotated[UserAccount, Depends(current_member)]
OwnerDependency = Annotated[UserAccount, Depends(current_owner)]


WS_UNAUTHENTICATED = 4401
WS_NO_ORGANIZATION = 4402
WEBSOCKET_AUTH_TIMEOUT_SECONDS = 10.0


async def authenticate_websocket(websocket: WebSocket) -> UserAccount | None:
    """Проверяет токен, присланный первым сообщением сокета.

    Токен идёт сообщением, а не параметром адреса: адрес попадает в логи
    сервера и прокси целиком, и вместе с ним туда попал бы ключ доступа.
    У браузерного `WebSocket` заголовков нет, поэтому первое сообщение —
    единственное место, куда его можно положить.

    Ожидание ограничено: сокет, открытый и замолчавший, иначе держал бы
    соединение и подписку неограниченно долго.

    `None` означает, что сокет уже закрыт с названной причиной.
    """
    try:
        payload = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=WEBSOCKET_AUTH_TIMEOUT_SECONDS,
        )
    except (TimeoutError, WebSocketDisconnect, RuntimeError, ValueError):
        await _close_websocket(websocket, WS_UNAUTHENTICATED, "Токен не предъявлен")
        return None

    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str):
        await _close_websocket(websocket, WS_UNAUTHENTICATED, "Первым сообщением ожидается токен")
        return None

    verifier: IdentityVerifier | None = getattr(
        websocket.app.state,
        "identity_verifier",
        None,
    )
    if verifier is None:
        await _close_websocket(
            websocket,
            WS_UNAUTHENTICATED,
            "Провайдер личности не настроен",
        )
        return None

    try:
        identity = await verifier.verify(token)
    except NotAuthenticatedError as error:
        await _close_websocket(websocket, WS_UNAUTHENTICATED, str(error))
        return None

    use_case = ResolveSignedInUser(
        SqlAlchemyUnitOfWork(websocket.app.state.session_factory),
        RedisEventPublisher(websocket.app.state.redis),
    )
    user = await use_case.execute(identity)
    if user.account is None:
        await _close_websocket(websocket, WS_NO_ORGANIZATION, NO_ORGANIZATION_DETAIL)
        return None

    return user.account


async def _close_websocket(websocket: WebSocket, code: int, reason: str) -> None:
    with suppress(RuntimeError):
        await websocket.close(code=code, reason=reason)
