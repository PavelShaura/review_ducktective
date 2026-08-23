from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.core.tenancy.entities import (
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    VerifiedIdentity,
)


@dataclass(frozen=True, kw_only=True)
class SignedInUser:
    """Кто вошёл и куда он принадлежит.

    Членства может не быть: личность подтверждена провайдером, а организации
    у человека ещё нет. Это не ошибка входа — это состояние, в котором
    предлагают создать организацию или принять приглашение.
    """

    identity: VerifiedIdentity
    account: UserAccount | None

    @property
    def belongs_to_organization(self) -> bool:
        return self.account is not None


class ResolveSignedInUser(TransactionalUseCase):
    """Членство вошедшего по подтверждённой личности.

    Заодно обновляет почту и отметку последнего входа: провайдер личности —
    источник правды про почту, а расхождение всплывает только здесь.
    Транзакция короткая и открывается на каждый запрос, поэтому запись идёт
    лишь тогда, когда что-то действительно изменилось.
    """

    async def execute(self, identity: VerifiedIdentity) -> SignedInUser:
        async with self._unit_of_work:
            account = await self._unit_of_work.user_accounts.find_by_identity(
                issuer=identity.issuer,
                subject=identity.subject,
            )
            if account is None:
                return SignedInUser(identity=identity, account=None)

            account.update_email(identity.email)
            account.record_seen(datetime.now(UTC))
            await self._commit_and_publish()

        return SignedInUser(identity=identity, account=account)
