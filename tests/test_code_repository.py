from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.events import (
    CodeRepositoryRegistered,
    EgressPolicyChanged,
)
from ducktective.core.code_repository.value_objects import (
    EgressPolicy,
    VcsProvider,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.types import (
    TenantId,
)


def build_repository(**overrides: object) -> CodeRepository:
    parameters: dict[str, object] = {
        "tenant_id": TenantId(uuid4()),
        "name": "sandbox",
        "vcs_provider": VcsProvider.LOCAL,
        "local_path": Path("/repos/sandbox"),
    }
    parameters.update(overrides)
    return CodeRepository.register(**parameters)  # type: ignore[arg-type]


def test_registration_records_event() -> None:
    repository = build_repository()

    events = repository.pull_events()

    assert len(events) == 1
    assert isinstance(events[0], CodeRepositoryRegistered)


def test_registration_trims_name() -> None:
    repository = build_repository(name="  sandbox  ")

    assert repository.name == "sandbox"


def test_blank_name_is_rejected() -> None:
    with pytest.raises(InvariantViolationError):
        build_repository(name="   ")


def test_remote_provider_requires_url() -> None:
    with pytest.raises(InvariantViolationError):
        build_repository(vcs_provider=VcsProvider.GITHUB, remote_url=None)


def test_default_policy_forbids_cloud() -> None:
    repository = build_repository()

    assert repository.egress_policy is EgressPolicy.LOCAL_ONLY
    assert repository.cloud_processing_allowed is False


def test_policy_change_records_event() -> None:
    repository = build_repository()
    repository.pull_events()

    repository.change_egress_policy(EgressPolicy.ALLOW_CLOUD)

    events = repository.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], EgressPolicyChanged)
    assert repository.cloud_processing_allowed is True


def test_policy_change_to_same_value_is_ignored() -> None:
    repository = build_repository()
    repository.pull_events()

    repository.change_egress_policy(EgressPolicy.LOCAL_ONLY)

    assert repository.pull_events() == []
