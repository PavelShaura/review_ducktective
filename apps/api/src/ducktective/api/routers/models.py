"""Модели организации.

Единица работы здесь тенантная, а не та, что у контура входа: `model_profile`
закрыт политикой базы наравне с остальными данными организации, и транзакция,
не назвавшая тенанта, не может ни прочитать чужую модель, ни записать свою.
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
    AddModelRequest,
    ModelPresetResponse,
    ModelProfileResponse,
    UpdateModelRequest,
)
from ducktective.api.security import (
    MemberDependency,
    OwnerDependency,
    TenantUnitOfWorkDependency,
)
from ducktective.application.models.manage import (
    AddModelCommand,
    AddModelProfile,
    DeleteModelProfile,
    ListModelProfiles,
    ModelNameTakenError,
    ModelNotFoundError,
    UpdateModelCommand,
    UpdateModelProfile,
)
from ducktective.core.exceptions import (
    AccessDeniedError,
    InvariantViolationError,
)
from ducktective.core.llm.presets import (
    MODEL_PRESETS,
)


router = APIRouter(prefix="/organization/models", tags=["models"])

NO_SECRET_DETAIL = (
    "Не задан MODELS_SECRET_KEY: ключ провайдера негде зашифровать. "
    "Сгенерируйте секрет командой `ducktective secret` и добавьте его в .env"
)


@router.get("/presets", response_model=list[ModelPresetResponse])
async def list_presets(member: MemberDependency) -> list[ModelPresetResponse]:
    """Известные провайдеры с заполненными полями.

    Ключа ни в одном нет: провайдеров, отвечающих без ключа, среди пригодных
    не нашлось, поэтому у каждого назван адрес, где ключ выдают бесплатно.
    """
    return [ModelPresetResponse.from_domain(preset) for preset in MODEL_PRESETS]


@router.get("", response_model=list[ModelProfileResponse])
async def list_models(
    member: MemberDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> list[ModelProfileResponse]:
    use_case = ListModelProfiles(unit_of_work, event_publisher)
    profiles = await use_case.execute(member.id)
    return [ModelProfileResponse.from_domain(profile) for profile in profiles]


@router.post("", response_model=ModelProfileResponse, status_code=status.HTTP_201_CREATED)
async def add_model(
    payload: AddModelRequest,
    owner: OwnerDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ModelProfileResponse:
    cipher = secret_cipher(settings)
    if cipher is None and payload.api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SECRET_DETAIL)

    use_case = AddModelProfile(unit_of_work, event_publisher, cipher or _NullCipher())

    try:
        profile = await use_case.execute(
            AddModelCommand(
                actor_id=owner.id,
                name=payload.name,
                model=payload.model,
                api_key=payload.api_key,
                provider=payload.provider,
                base_url=payload.base_url,
                trust=payload.trust,
                supports_tools=payload.supports_tools,
                context_window=payload.context_window,
                note=payload.note,
            )
        )
    except ModelNameTakenError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return ModelProfileResponse.from_domain(profile)


@router.patch("/{profile_id}", response_model=ModelProfileResponse)
async def update_model(
    profile_id: UUID,
    payload: UpdateModelRequest,
    owner: OwnerDependency,
    settings: SettingsDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> ModelProfileResponse:
    cipher = secret_cipher(settings)
    if cipher is None and payload.api_key:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SECRET_DETAIL)

    use_case = UpdateModelProfile(unit_of_work, event_publisher, cipher or _NullCipher())

    try:
        profile = await use_case.execute(
            UpdateModelCommand(
                actor_id=owner.id,
                profile_id=profile_id,
                model=payload.model,
                api_key=payload.api_key,
                base_url=payload.base_url,
                trust=payload.trust,
                supports_tools=payload.supports_tools,
                context_window=payload.context_window,
                note=payload.note,
                is_enabled=payload.is_enabled,
            )
        )
    except ModelNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvariantViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error

    return ModelProfileResponse.from_domain(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    profile_id: UUID,
    owner: OwnerDependency,
    unit_of_work: TenantUnitOfWorkDependency,
    event_publisher: EventPublisherDependency,
) -> None:
    use_case = DeleteModelProfile(unit_of_work, event_publisher)

    try:
        await use_case.execute(owner.id, profile_id)
    except ModelNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except AccessDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error


class _NullCipher:
    """Заглушка для правок, не касающихся ключа.

    Модель без ключа завести можно — совместимый сервер в своей сети часто
    его не спрашивает, — и требовать секрет шифрования ради такой записи
    значило бы усложнять первый запуск.
    """

    def encrypt(self, secret: str) -> str:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SECRET_DETAIL)

    def decrypt(self, ciphertext: str) -> str:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_SECRET_DETAIL)
