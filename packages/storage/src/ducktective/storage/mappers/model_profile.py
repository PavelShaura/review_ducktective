from ducktective.core.llm.model_profile import (
    ModelProfile,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.models.model_profile import (
    ModelProfileModel,
)


def to_domain(model: ModelProfileModel) -> ModelProfile:
    return ModelProfile(
        id=model.id,
        tenant_id=TenantId(model.tenant_id),
        name=model.name,
        model=model.model,
        provider=model.provider,
        base_url=model.base_url,
        encrypted_api_key=model.encrypted_api_key,
        trust=model.trust,
        supports_tools=model.supports_tools,
        context_window=model.context_window,
        note=model.note,
        is_enabled=model.is_enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def to_model(profile: ModelProfile) -> ModelProfileModel:
    return ModelProfileModel(
        id=profile.id,
        tenant_id=profile.tenant_id,
        name=profile.name,
        model=profile.model,
        provider=profile.provider,
        base_url=profile.base_url,
        encrypted_api_key=profile.encrypted_api_key,
        trust=profile.trust,
        supports_tools=profile.supports_tools,
        context_window=profile.context_window,
        note=profile.note,
        is_enabled=profile.is_enabled,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def apply_changes(model: ModelProfileModel, profile: ModelProfile) -> None:
    model.model = profile.model
    model.provider = profile.provider
    model.base_url = profile.base_url
    model.encrypted_api_key = profile.encrypted_api_key
    model.trust = profile.trust
    model.supports_tools = profile.supports_tools
    model.context_window = profile.context_window
    model.note = profile.note
    model.is_enabled = profile.is_enabled
    model.updated_at = profile.updated_at
