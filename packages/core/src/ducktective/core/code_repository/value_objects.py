from enum import (
    StrEnum,
)


class VcsProvider(StrEnum):
    LOCAL = "local"
    GITHUB = "github"
    BITBUCKET = "bitbucket"


class EgressPolicy(StrEnum):
    """Разрешено ли отправлять код репозитория внешним провайдерам моделей."""

    LOCAL_ONLY = "local_only"
    ALLOW_CLOUD = "allow_cloud"
