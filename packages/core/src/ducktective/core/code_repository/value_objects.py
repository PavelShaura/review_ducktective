from enum import (
    StrEnum,
)


class VcsProvider(StrEnum):
    LOCAL = "local"
    GITHUB = "github"
    BITBUCKET = "bitbucket"


class ModelTrust(StrEnum):
    """Насколько далеко код уезжает ради ответа модели.

    Уровни упорядочены: каждый следующий выпускает код дальше предыдущего.
    Различать удалённые модели по этому признаку обязательно — иначе провайдер
    с обязательством не хранить запросы оказывается в одной корзине
    с бесплатным маршрутом, который на них учится (D-028).
    """

    LOCAL = "local"
    PRIVATE_REMOTE = "private_remote"
    TRAINING_REMOTE = "training_remote"

    @property
    def rank(self) -> int:
        return _TRUST_ORDER.index(self)

    def is_allowed_by(self, limit: "ModelTrust") -> bool:
        return self.rank <= limit.rank


_TRUST_ORDER: tuple[ModelTrust, ...] = (
    ModelTrust.LOCAL,
    ModelTrust.PRIVATE_REMOTE,
    ModelTrust.TRAINING_REMOTE,
)


class EgressPolicy(StrEnum):
    """Как далеко разрешено уезжать коду этого репозитория.

    Значения `local_only` и `allow_cloud` сохранены с первой версии: первое
    не выпускает код никуда, второе — только к провайдерам, обещавшим не
    учиться на запросах. Третье заведено отдельно, потому что бесплатные
    тиры такого обещания не дают, а согласие на это должно быть явным.
    """

    LOCAL_ONLY = "local_only"
    ALLOW_CLOUD = "allow_cloud"
    ALLOW_TRAINING_CLOUD = "allow_training_cloud"

    @property
    def max_trust(self) -> ModelTrust:
        if self is EgressPolicy.LOCAL_ONLY:
            return ModelTrust.LOCAL
        if self is EgressPolicy.ALLOW_CLOUD:
            return ModelTrust.PRIVATE_REMOTE
        return ModelTrust.TRAINING_REMOTE
