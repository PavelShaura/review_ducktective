"""Подключения организации к провайдерам моделей.

Единица работы здесь тенантная, а не та, что у контура входа:
`provider_connection` закрыт политикой базы наравне с остальными данными
организации, и транзакция, не назвавшая тенанта, не может ни прочитать
чужое подключение, ни записать своё.
"""

from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from ducktective.api.dependencies import (
    EventPublisherDependency,
    SettingsDependency,
    secret_cipher,
)
from ducktective.api.schemas.models import (
    AddConnectionRequest,
    ModelPresetResponse,
    ProbeConnectionRequest,
    ProbeConnectionResponse,
    ProviderConnectionResponse,
    UpdateConnectionRequest,
)
from ducktective.api.security import (
    MemberDependency,
    OwnerDependency,
    TenantUnitOfWorkDependency,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.application.models.manage import (
    AddConnectionCommand,
    AddProviderConnection,
    ConnectionNameTakenError,
    ConnectionNotFoundError,
    DeleteProviderConnection,
    ListProviderConnections,
    UpdateConnectionCommand,
    UpdateProviderConnection,
)
from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.exceptions import (
    AccessDeniedError,
    InvariantViolationError,
)
from ducktective.core.llm.presets import (
    MODEL_PRESETS,
)
from ducktective.llm.probe import (
    probe_model,
)
from ducktective.llm.router import (
    ModelChoice,
)


router = APIRouter(prefix="/organization/models", tags=["models"])


@router.get("/presets", response_model=list[ModelPresetResponse])
async def list_presets(member: MemberDependency) -> list[ModelPresetResponse]:
    """Известные провайдеры с заполненными полями.

    Ключа ни в одном нет: провайдеров, отвечающих без ключа, среди пригодных
    не нашлось, поэтому у каждого назван адрес, где ключ выдают бесплатно.
    """
    return [ModelPresetResponse.from_domain(preset) for preset in MODEL_PRESETS]


@router.post("/probe", response_model=ProbeConnectionResponse)
async def probe_connection(
    payload: ProbeConnectionRequest,
    owner: OwnerDependency,
) -> ProbeConnectionResponse:
    """Спрашивает провайдера, работают ли эти настройки, и что он предлагает.

    Иначе первым испытанием ключа станет настоящий вопрос: человек введёт
    его, задаст вопрос и через минуту получит отказ, не понимая, дело
    в ключе, адресе или имени модели.
    """
    result = await probe_model(
        ModelChoice(
            name="probe",
            model=payload.model,
            provider=payload.provider or payload.model.split("/", 1)[0],
            api_base=payload.base_url or None,
            api_key=payload.api_key or None,
            trust=ModelTrust.TRAINING_REMOTE,
        )
    )
    return ProbeConnectionResponse(
        is_reachable=result.is_reachable,
        detail=result.detail,
        models=list(result.models),
    )


@router.get("", response_model=list[ProviderConnectionResponse])
async def list_connections(
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> list[ProviderConnectionResponse]:
    use_case = ListProviderConnections(unit_of_work, event_publisher)
    connections = await use_case.execute(member.id)
    return [ProviderConnectionResponse.from_domain(item) for item in connections]


@router.post("", response_model=ProviderConnectionResponse, status_code=status.HTTP_201_CREATED)
async def add_connection(
    payload: AddConnectionRequest,
    owner: OwnerDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ProviderConnectionResponse:
    use_case = AddProviderConnection(unit_of_work, event_publisher, secret_cipher(settings))

    try:
        connection = await use_case.execute(
            AddConnectionCommand(
                actor_id=owner.id,
                name=payload.name,
                api_key=payload.api_key,
                default_model=payload.default_model,
                catalogue=tuple(payload.catalogue),
                provider=payload.provider,
                base_url=payload.base_url,
                trust=payload.trust,
                supports_tools=payload.supports_tools,
                context_window=payload.context_window,
                note=payload.note,
            )
        )
    except ConnectionNameTakenError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except ApplicationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return ProviderConnectionResponse.from_domain(connection)


@router.patch("/{connection_id}", response_model=ProviderConnectionResponse)
async def update_connection(
    connection_id: UUID,
    payload: UpdateConnectionRequest,
    owner: OwnerDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ProviderConnectionResponse:
    use_case = UpdateProviderConnection(unit_of_work, event_publisher, secret_cipher(settings))

    try:
        connection = await use_case.execute(
            UpdateConnectionCommand(
                actor_id=owner.id,
                connection_id=connection_id,
                default_model=payload.default_model,
                api_key=payload.api_key,
                base_url=payload.base_url,
                trust=payload.trust,
                supports_tools=payload.supports_tools,
                context_window=payload.context_window,
                note=payload.note,
                is_enabled=payload.is_enabled,
            )
        )
    except ConnectionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except ApplicationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

    return ProviderConnectionResponse.from_domain(connection)


@router.post("/{connection_id}/catalogue", response_model=ProviderConnectionResponse)
async def refresh_catalogue(
    connection_id: UUID,
    owner: OwnerDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ProviderConnectionResponse:
    """Переспрашивает у провайдера, какие модели он теперь предлагает.

    Состав подписки меняется от месяца к месяцу, и записанный однажды
    перечень устаревает молча: модель исчезает, а выбор в форме остаётся.
    """
    cipher = secret_cipher(settings)
    listing = ListProviderConnections(unit_of_work, event_publisher)
    connections = await listing.execute(owner.id)
    target = next((item for item in connections if item.id == connection_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подключение не найдено")

    api_key = ""
    if target.encrypted_api_key and cipher is not None:
        api_key = cipher.decrypt(target.encrypted_api_key)

    result = await probe_model(
        ModelChoice(
            name=target.name,
            model=target.default_model,
            provider=target.provider,
            api_base=target.base_url or None,
            api_key=api_key or None,
            trust=target.trust,
        )
    )
    if not result.is_reachable:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, result.detail)

    use_case = UpdateProviderConnection(unit_of_work, event_publisher, cipher)
    connection = await use_case.execute(
        UpdateConnectionCommand(
            actor_id=owner.id,
            connection_id=connection_id,
            catalogue=result.models,
        )
    )
    return ProviderConnectionResponse.from_domain(connection)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    owner: OwnerDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    use_case = DeleteProviderConnection(unit_of_work, event_publisher)

    try:
        await use_case.execute(owner.id, connection_id)
    except ConnectionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
