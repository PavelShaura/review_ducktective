from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Protocol,
    Self,
)
from uuid import (
    UUID,
    uuid4,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    TenantId,
)


ModelProfileId = UUID

MAX_NAME_LENGTH = 64


@dataclass(kw_only=True)
class ModelProfile(AggregateRoot):
    """Удалённая модель, заведённая организацией.

    Ключ хранится зашифрованным и наружу не отдаётся никогда — ни владельцу,
    ни в списке: подтвердить, что он задан, можно фактом успешного вызова,
    а показать его второй раз незачем.

    Уровень доверия задаёт человек, а не провайдер: обещание не учиться на
    запросах — вопрос договора, и приложению взять его неоткуда. По умолчанию
    самый строгий из удалённых — ошибиться в эту сторону дешевле (D-028).
    """

    id: ModelProfileId
    tenant_id: TenantId
    name: str
    model: str
    provider: str
    base_url: str
    encrypted_api_key: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    note: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        name: str,
        model: str,
        encrypted_api_key: str,
        provider: str = "",
        base_url: str = "",
        trust: ModelTrust = ModelTrust.TRAINING_REMOTE,
        supports_tools: bool = True,
        context_window: int = 0,
        note: str = "",
    ) -> Self:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > MAX_NAME_LENGTH:
            raise InvariantViolationError(f"Имя модели — от одного до {MAX_NAME_LENGTH} знаков")
        if not model.strip():
            raise InvariantViolationError("Не указан идентификатор модели у провайдера")
        if trust is ModelTrust.LOCAL:
            raise InvariantViolationError(
                "Локальная модель задаётся настройками сервера, а не организацией"
            )

        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            name=clean_name,
            model=model.strip(),
            provider=provider.strip(),
            base_url=base_url.strip(),
            encrypted_api_key=encrypted_api_key,
            trust=trust,
            supports_tools=supports_tools,
            context_window=context_window,
            note=note.strip(),
            is_enabled=True,
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        trust: ModelTrust | None = None,
        supports_tools: bool | None = None,
        context_window: int | None = None,
        note: str | None = None,
        is_enabled: bool | None = None,
        encrypted_api_key: str | None = None,
    ) -> None:
        """Правит профиль. Ключ меняется только тогда, когда прислан новый.

        Пустое поле ключа в форме означает «оставить прежний», а не «стереть»:
        иначе правка окна контекста молча ломала бы работающую модель.
        """
        if model is not None and model.strip():
            self.model = model.strip()
        if base_url is not None:
            self.base_url = base_url.strip()
        if trust is not None:
            if trust is ModelTrust.LOCAL:
                raise InvariantViolationError(
                    "Локальная модель задаётся настройками сервера, а не организацией"
                )
            self.trust = trust
        if supports_tools is not None:
            self.supports_tools = supports_tools
        if context_window is not None:
            self.context_window = context_window
        if note is not None:
            self.note = note.strip()
        if is_enabled is not None:
            self.is_enabled = is_enabled
        if encrypted_api_key:
            self.encrypted_api_key = encrypted_api_key

        self.updated_at = datetime.now(UTC)


class SecretCipher(Protocol):
    """Шифрование секретов, хранимых в базе.

    Порт объявлен доменом, потому что правило «ключ провайдера не лежит
    в базе открытым» — требование к данным, а не деталь хранилища. Чем
    именно он зашифрован, домену неизвестно.
    """

    def encrypt(self, secret: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class ModelProfileRepository(Protocol):
    def add(self, profile: ModelProfile) -> None: ...

    async def get(self, profile_id: ModelProfileId) -> ModelProfile: ...

    async def list_for_tenant(self, tenant_id: TenantId) -> list[ModelProfile]: ...

    async def find_by_name(self, tenant_id: TenantId, name: str) -> ModelProfile | None: ...

    async def remove(self, profile: ModelProfile) -> None: ...
