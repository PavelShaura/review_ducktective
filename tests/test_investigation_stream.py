from typing import (
    Any,
)

from starlette.websockets import (
    WebSocketState,
)

from ducktective.api.routers.investigation_stream import (
    WS_FORBIDDEN,
    _close,
    _send,
)


class FakeWebSocket:
    """Сокет, у которого клиент может уйти в любой момент."""

    def __init__(
        self,
        *,
        state: WebSocketState = WebSocketState.CONNECTED,
        fails_with: Exception | None = None,
    ) -> None:
        self.client_state = state
        self.sent: list[dict[str, Any]] = []
        self.closed_with: int | None = None
        self._fails_with = fails_with

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._fails_with is not None:
            raise self._fails_with
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        if self._fails_with is not None:
            raise self._fails_with
        self.closed_with = code


async def test_step_reaches_a_live_client() -> None:
    websocket = FakeWebSocket()

    delivered = await _send(websocket, {"cursor": 1})  # type: ignore[arg-type]

    assert delivered is True
    assert websocket.sent == [{"cursor": 1}]


async def test_closed_socket_is_not_written_to() -> None:
    websocket = FakeWebSocket(state=WebSocketState.DISCONNECTED)

    delivered = await _send(websocket, {"cursor": 1})  # type: ignore[arg-type]

    assert delivered is False
    assert websocket.sent == []


async def test_client_leaving_mid_send_is_not_a_failure() -> None:
    """Транспорт закрывается между проверкой и записью — это норма.

    В разработке React монтирует подписку дважды и первый сокет закрывает
    сам; в бою страницу просто закрывают. Раньше запись в закрытый транспорт
    роняла обработчик трейсбеком на весь лог.
    """
    websocket = FakeWebSocket(fails_with=RuntimeError("the handler is closed"))

    delivered = await _send(websocket, {"cursor": 1})  # type: ignore[arg-type]

    assert delivered is False


async def test_refusal_reaches_a_live_client() -> None:
    websocket = FakeWebSocket()

    await _close(websocket, WS_FORBIDDEN, "Прогон принадлежит другому тенанту")  # type: ignore[arg-type]

    assert websocket.closed_with == WS_FORBIDDEN


async def test_refusal_to_a_client_who_already_left_is_silent() -> None:
    """Закрывать закрытое — вторая ошибка поверх первой, и в логе видна она."""
    websocket = FakeWebSocket(state=WebSocketState.DISCONNECTED)

    await _close(websocket, WS_FORBIDDEN, "Прогон принадлежит другому тенанту")  # type: ignore[arg-type]

    assert websocket.closed_with is None
