from enum import (
    StrEnum,
)
from pathlib import (
    Path,
)

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from ducktective.config.embedding import (
    DEFAULT_BACKEND_KEY,
    EmbeddingBackend,
    load_embedding_backends,
)


class DeploymentProfile(StrEnum):
    DEV = "dev"
    AIRGAPPED = "airgapped"
    FULL = "full"


class Settings(BaseSettings):
    """Единые настройки для всех приложений.

    Общий класс нужен, чтобы api и воркер собирали одинаковые зависимости:
    расхождение конфигурации между ними приводило бы к разным моделям и
    разным политикам egress в одном и том же прогоне.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_log_level: str = "INFO"
    app_log_file: Path | None = None
    """Файл, куда дописываются логи в формате JSON Lines.

    Не задан по умолчанию: в контейнере логи собирают со stdout, и второй
    файл там только занимал бы диск. При локальном запуске без сборщика
    файл — единственное место, где прогон остаётся после закрытия терминала.
    """
    installation_admin_emails: str = ""
    """Почты администраторов установки через запятую.

    Журнал общий для всех организаций, поэтому владельцу организации его
    показывать нельзя: рядом лежат строки чужих прогонов. Администратор
    установки стоит над организациями, и его список живёт в настройках,
    а не в базе — там нет строки, которой он принадлежал бы.
    """

    database_url: str = ""
    database_pool_size: int = 10
    database_pool_max_overflow: int = 5
    database_auto_migrate: bool = False
    """Накатывать ли миграции при старте службы.

    Выключено по умолчанию: в развёртывании схему меняют осознанно и в свой
    момент, а не первым поднявшимся контейнером. Без этого флага отставшая
    база останавливает старт с названными ревизиями — вместо 500 на каждый
    запрос. Для локальной разработки флаг включён в `.env.example`.
    """

    redis_url: str = ""

    deployment_profile: DeploymentProfile = DeploymentProfile.DEV

    local_llm_provider: str = "ollama"
    local_llm_base_url: str = "http://localhost:11434"
    local_llm_api_key: str = ""
    local_embedding_model: str = "nomic-embed-text-q8"
    local_embedding_base_url: str = "http://localhost:11434/v1"
    """Эмбеддер из compose: Ollama на CPU, независимо от того, где живёт LLM."""
    local_embedding_title: str = "Ollama из compose"
    local_embedding_note: str = (
        "Считает на CPU и медленно, зато всегда рядом с приложением: по этому "
        "набору векторов идёт поиск по смыслу по умолчанию. Отдельно поднятая "
        "модель на GPU считает быстрее — если пишет в тот же набор, посчитанное "
        "ею подхватится здесь."
    )
    local_embedding_vector_set: str = "nomic-embed-text-v1.5"
    """Имя набора векторов эмбеддера по умолчанию."""
    embedding_backends_file: Path = Path("embedding_backends.json")
    """Дополнительные серверы эмбеддингов, выбираемые при индексации."""
    embedding_dimensions: int = 768
    context_token_budget: int = 2000
    local_reranker_model: str = "bge-reranker-v2-m3"
    local_review_model: str = "qwen2.5-coder:14b"
    local_review_model_supports_tools: bool = True
    """Локальная модель умеет вызывать инструменты.

    От этого зависит, доступен ли агентный режим ревью: без вызовов инструментов
    он вырождается в одноразовый проход. Признак задаётся здесь, а не выясняется
    у сервера: локальные сборки на неподдерживаемое поле отвечают по-разному.
    """

    local_chat_model: str = ""
    """Модель разговора, если она должна отличаться от модели ревью.

    Пусто — берётся модель ревью. Разделение нужно потому, что задачи разные:
    ревью читает патч и укладывается в один проход, а разговор строит цепочку
    из перечня файлов, чтения и поиска — и на этом небольшие сборки ломаются.
    Замерено: на вопрос о фреймворке фронта сборка на 4B перечислила файлы,
    открыла один и назвала библиотеку из вендорного кода; сборка на 12B
    открыла два и назвала настоящий фреймворк, потратив вчетверо больше
    времени.
    """

    local_review_model_context_window: int = 16384
    """Окно, с которым локальная модель загружена на сервере, ноль — неизвестно.

    Называет его сервер, а не модель: у LM Studio `max_context_length` и
    `loaded_context_length` расходятся на порядок, и работает второе. Значение
    читает роутер: узлу, которому нужен диалог с инструментами, при меньшем
    окне достаётся облачная модель, если политика репозитория её разрешает.
    """

    models_secret_key: str = ""
    """Секрет шифрования ключей провайдеров, хранимых организацией.

    Без него модели, заведённые из интерфейса, сохранять негде: ключ лёг бы
    в базу открытым, а это ровно то, чего решение D-029 не допускает.
    Значение печатает `ducktective secret`; потеря секрета означает ввод
    ключей заново, и об этом сказано в интерфейсе.
    """

    remote_models_file: Path = Path("remote_models.json")
    """Реестр удалённых моделей: имя, адрес, окно, умения, уровень доверия.

    Файлом, а не переменными: моделей больше одной, и у каждой полдюжины
    признаков. Ключи в файл не попадают — там названы только имена
    переменных окружения, из которых их брать (D-028).
    """

    cloud_review_model: str = "anthropic/claude-sonnet-5"
    cloud_review_model_context_window: int = 200000
    """Одна удалённая модель на случай, когда реестра нет.

    Совместимость с установками, поднятыми до реестра: пара «модель и ключ»
    там задавалась переменными, и молча перестать её читать значило бы
    сломать работающее.
    """
    llm_timeout_seconds: float = 180.0
    llm_cache_ttl_seconds: int = 7 * 24 * 3600
    llm_max_output_tokens: int = 4096
    """Сколько токенов ответа запрашивается у модели.

    Место под ответ резервируется в окне модели, поэтому значение вычитается
    из того, что остаётся под сам дифф: при окне 8192 запрошенные 4096 съедают
    половину. У reasoning-моделей на размышления уходит большая часть выхода,
    и там снижать это число нельзя — нужно поднимать окно.
    """

    agent_max_steps: int = 25
    """Потолок обращений к модели за одно агентное расследование файла.

    Страховка от модели, ходящей по кругу. Рабочий предел — окно модели:
    цикл заканчивается, когда диалог его заполнил.
    """

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    otel_exporter_otlp_endpoint: str = ""

    repositories_root: Path = Path("./repos")

    review_queue_name: str = "ducktective:reviews"
    review_job_timeout_seconds: int = 1800
    review_lock_wait_seconds: float = 240.0
    """Сколько новая попытка ждёт, пока прежняя отпустит прогон.

    Прежняя узнаёт об отмене перед очередным обращением к модели, то есть
    с задержкой до одного вызова: при `LLM_TIMEOUT_SECONDS=180` ожидание
    в четыре минуты покрывает самый долгий из них с запасом. Не дождавшись,
    задание не висит дальше — попытка, не отвечающая столько времени,
    ждать себя не заслуживает, а слот воркера один на два прогона.
    """

    oidc_issuer: str = ""
    """Адрес realm провайдера личности, пусто — вход выключен.

    Выключенный вход оставлен ради автономного режима CLI и тестов: там
    процесс идёт от одного человека на своей машине, и спрашивать у него
    токен незачем. Для api и фронта значение обязательно — без него
    поднимать сетевую службу с открытыми данными нельзя.
    """

    oidc_audience: str = "ducktective-api"
    oidc_client_id: str = "ducktective-web"
    oidc_device_client_id: str = "ducktective-cli"

    mcp_http_host: str = "127.0.0.1"
    mcp_http_port: int = 8090

    @property
    def authentication_required(self) -> bool:
        """Вход обязателен там, где задан провайдер личности."""
        return bool(self.oidc_issuer)

    @property
    def cloud_providers_allowed(self) -> bool:
        """В air-gapped профиле облачные провайдеры запрещены на уровне конфигурации."""
        return self.deployment_profile is not DeploymentProfile.AIRGAPPED

    def embedding_backends(self) -> tuple[EmbeddingBackend, ...]:
        """Все серверы эмбеддингов: из compose по умолчанию плюс реестр."""
        default = EmbeddingBackend(
            key=DEFAULT_BACKEND_KEY,
            title=self.local_embedding_title,
            model=self.local_embedding_model,
            base_url=self.local_embedding_base_url or self.local_llm_base_url,
            api_key=self.local_llm_api_key,
            vector_set=self.local_embedding_vector_set,
            note=self.local_embedding_note,
        )
        return (default, *load_embedding_backends(self.embedding_backends_file))

    @property
    def installation_admins(self) -> frozenset[str]:
        """Почты администраторов в нижнем регистре: провайдер отдаёт их как есть."""
        return frozenset(
            email.strip().lower()
            for email in self.installation_admin_emails.split(",")
            if email.strip()
        )

    def require_database_url(self) -> str:
        """Адреса хранилищ не обязательны: автономный режим CLI работает без них."""
        if not self.database_url:
            raise ValueError("Не задан DATABASE_URL — он нужен всем режимам, кроме --no-store")
        return self.database_url

    def require_redis_url(self) -> str:
        if not self.redis_url:
            raise ValueError("Не задан REDIS_URL — он нужен всем режимам, кроме --no-store")
        return self.redis_url
