from datetime import (
    datetime,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.core.code_repository.value_objects import (
    ModelTrust,
)
from ducktective.core.llm.model_profile import (
    ModelProfile,
)
from ducktective.core.llm.presets import (
    ModelPreset,
)


class ModelProfileResponse(BaseModel):
    """Модель организации. Ключ не отдаётся — только признак, что он задан."""

    id: UUID
    name: str
    model: str
    provider: str
    base_url: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    note: str
    is_enabled: bool
    has_api_key: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, profile: ModelProfile) -> "ModelProfileResponse":
        return cls(
            id=profile.id,
            name=profile.name,
            model=profile.model,
            provider=profile.provider,
            base_url=profile.base_url,
            trust=profile.trust,
            supports_tools=profile.supports_tools,
            context_window=profile.context_window,
            note=profile.note,
            is_enabled=profile.is_enabled,
            has_api_key=bool(profile.encrypted_api_key),
            created_at=profile.created_at,
        )


class AddModelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=255)
    api_key: str = ""
    provider: str = ""
    base_url: str = ""
    trust: ModelTrust = ModelTrust.TRAINING_REMOTE
    supports_tools: bool = True
    context_window: int = 0
    note: str = ""


class UpdateModelRequest(BaseModel):
    """Правка модели. Пустой ключ значит «оставить прежний», а не «стереть»."""

    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    trust: ModelTrust | None = None
    supports_tools: bool | None = None
    context_window: int | None = None
    note: str | None = None
    is_enabled: bool | None = None


class ModelPresetResponse(BaseModel):
    """Известный провайдер с заполненными полями и адресом, где взять ключ."""

    key: str
    title: str
    model: str
    provider: str
    base_url: str
    trust: ModelTrust
    supports_tools: bool
    context_window: int
    signup_url: str
    note: str

    @classmethod
    def from_domain(cls, preset: ModelPreset) -> "ModelPresetResponse":
        return cls(
            key=preset.key,
            title=preset.title,
            model=preset.model,
            provider=preset.provider,
            base_url=preset.base_url,
            trust=preset.trust,
            supports_tools=preset.supports_tools,
            context_window=preset.context_window,
            signup_url=preset.signup_url,
            note=preset.note,
        )
