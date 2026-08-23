from dataclasses import (
    dataclass,
    field,
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


ConnectionId = UUID

MAX_NAME_LENGTH = 64
NAME_SEPARATOR = "/"


@dataclass(kw_only=True)
class ProviderConnection(AggregateRoot):
    """Доступ организации к провайдеру моделей: ключ, адрес и его каталог.

    Подключение, а не модель, потому что подписка даёт их два десятка и
    состав меняется от месяца к месяцу. Заводить каждую руками значит
    заводить их заново после каждого обновления у провайдера.

    Ключ хранится зашифрованным и наружу не отдаётся никогда — ни владельцу,
    ни в списке: подтвердить, что он задан, можно фактом успешного вызова.

    Уровень доверия задаёт человек, а не провайдер: обещание не учиться на
    запросах — вопрос договора, и приложению взять его неоткуда. По умолчанию
    самый строгий из удалённых — ошибиться в эту сторону дешевле (D-028).
    """

    id: ConnectionId
    tenant_id: TenantId
    name: str
    provider: str
    base_url: str
    encrypted_api_key: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    note: str
    is_enabled: bool
    default_model: str
    """Модель, которой отвечает подключение, пока человек не выбрал другую."""

    catalogue: list[str] = field(default_factory=list)
    """Что провайдер отдал по своему перечню моделей.

    Хранится, потому что список нужен при каждом запуске прогона и разговора,
    а спрашивать провайдера на каждое открытие формы значит ставить его
    доступность условием показа страницы.
    """

    catalogue_refreshed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        name: str,
        encrypted_api_key: str,
        default_model: str = "",
        provider: str = "",
        base_url: str = "",
        trust: ModelTrust = ModelTrust.TRAINING_REMOTE,
        supports_tools: bool = True,
        context_window: int = 0,
        note: str = "",
        catalogue: list[str] | None = None,
    ) -> Self:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > MAX_NAME_LENGTH:
            raise InvariantViolationError(
                f"Имя подключения — от одного до {MAX_NAME_LENGTH} знаков"
            )
        if NAME_SEPARATOR in clean_name:
            raise InvariantViolationError(
                "В имени подключения не может быть косой черты: ею отделяется модель"
            )
        if trust is ModelTrust.LOCAL:
            raise InvariantViolationError(
                "Локальная модель задаётся настройками сервера, а не организацией"
            )

        listed = list(catalogue or [])
        if not default_model and not listed:
            raise InvariantViolationError(
                "Нужна хотя бы одна модель: назовите её или получите перечень у провайдера"
            )

        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            name=clean_name,
            provider=provider.strip(),
            base_url=base_url.strip(),
            encrypted_api_key=encrypted_api_key,
            trust=trust,
            supports_tools=supports_tools,
            context_window=context_window,
            note=note.strip(),
            is_enabled=True,
            default_model=(default_model or listed[0]).strip(),
            catalogue=listed,
            catalogue_refreshed_at=now if listed else None,
            created_at=now,
            updated_at=now,
        )

    @property
    def models(self) -> tuple[str, ...]:
        """Модели, которые это подключение предлагает на выбор.

        Каталог, а если его нет — одна названная модель: подключение без
        единой модели существовать не может, и проверка стоит в `create`.
        """
        if self.catalogue:
            return tuple(self.catalogue)
        return (self.default_model,) if self.default_model else ()

    def offers(self, model: str) -> bool:
        return model in self.models

    def qualified(self, model: str) -> str:
        """Имя модели, каким его видит человек в списке выбора.

        С именем подключения впереди: одна и та же открытая модель бывает
        у двух провайдеров сразу, и без приставки выбор неразличим.
        """
        return f"{self.name}{NAME_SEPARATOR}{model}"

    def refresh_catalogue(self, models: list[str]) -> None:
        """Принимает перечень, полученный у провайдера.

        Пустой ответ каталог не стирает: провайдер мог ответить неудачно,
        а забыть список значит оставить организацию без выбора там, где
        вчера он был.
        """
        if not models:
            return

        self.catalogue = list(models)
        if self.default_model not in self.catalogue:
            self.default_model = self.catalogue[0]
        self.catalogue_refreshed_at = datetime.now(UTC)
        self.updated_at = self.catalogue_refreshed_at

    def update(
        self,
        *,
        default_model: str | None = None,
        base_url: str | None = None,
        trust: ModelTrust | None = None,
        supports_tools: bool | None = None,
        context_window: int | None = None,
        note: str | None = None,
        is_enabled: bool | None = None,
        encrypted_api_key: str | None = None,
    ) -> None:
        """Правит подключение. Ключ меняется только тогда, когда прислан новый.

        Пустое поле ключа в форме означает «оставить прежний», а не «стереть»:
        иначе правка окна контекста молча ломала бы работающее подключение.
        """
        if default_model is not None and default_model.strip():
            self.default_model = default_model.strip()
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


class ProviderConnectionRepository(Protocol):
    def add(self, connection: ProviderConnection) -> None: ...

    async def get(self, connection_id: ConnectionId) -> ProviderConnection: ...

    async def list_for_tenant(self, tenant_id: TenantId) -> list[ProviderConnection]: ...

    async def find_by_name(self, tenant_id: TenantId, name: str) -> ProviderConnection | None: ...

    async def remove(self, connection: ProviderConnection) -> None: ...
