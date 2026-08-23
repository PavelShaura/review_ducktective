from ducktective.core.llm.provider_connection import (
    ProviderConnection,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.models.provider_connection import (
    ProviderConnectionModel,
)


def to_domain(model: ProviderConnectionModel) -> ProviderConnection:
    return ProviderConnection(
        id=model.id,
        tenant_id=TenantId(model.tenant_id),
        name=model.name,
        default_model=model.default_model,
        catalogue=list(model.catalogue or []),
        catalogue_refreshed_at=model.catalogue_refreshed_at,
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


def to_model(connection: ProviderConnection) -> ProviderConnectionModel:
    return ProviderConnectionModel(
        id=connection.id,
        tenant_id=connection.tenant_id,
        name=connection.name,
        default_model=connection.default_model,
        catalogue=list(connection.catalogue),
        catalogue_refreshed_at=connection.catalogue_refreshed_at,
        provider=connection.provider,
        base_url=connection.base_url,
        encrypted_api_key=connection.encrypted_api_key,
        trust=connection.trust,
        supports_tools=connection.supports_tools,
        context_window=connection.context_window,
        note=connection.note,
        is_enabled=connection.is_enabled,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def apply_changes(model: ProviderConnectionModel, connection: ProviderConnection) -> None:
    model.default_model = connection.default_model
    model.catalogue = list(connection.catalogue)
    model.catalogue_refreshed_at = connection.catalogue_refreshed_at
    model.provider = connection.provider
    model.base_url = connection.base_url
    model.encrypted_api_key = connection.encrypted_api_key
    model.trust = connection.trust
    model.supports_tools = connection.supports_tools
    model.context_window = connection.context_window
    model.note = connection.note
    model.is_enabled = connection.is_enabled
    model.updated_at = connection.updated_at
