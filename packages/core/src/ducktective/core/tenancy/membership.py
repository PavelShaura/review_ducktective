from collections.abc import (
    Sequence,
)

from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.tenancy.entities import (
    UserAccount,
)
from ducktective.core.tenancy.value_objects import (
    TenantRole,
)


def ensure_owner_remains(members: Sequence[UserAccount], *, changing: UserAccount) -> None:
    """Организация не остаётся без владельца.

    Правило пересекает агрегаты — участники хранятся по одному, а инвариант
    про их совокупность, — поэтому живёт функцией домена, а не методом
    учётной записи: экземпляр о существовании остальных не знает.

    Проверяется и при смене роли, и при исключении: оба действия способны
    оставить организацию, репозитории которой некому передать.
    """
    if not changing.is_owner:
        return

    other_owners = [member for member in members if member.is_owner and member.id != changing.id]
    if not other_owners:
        raise InvariantViolationError("В организации должен остаться хотя бы один владелец")


def ensure_role_assignable(role: TenantRole) -> None:
    """Роль назначается только из известных домену.

    Строка из запроса доходит сюда уже разобранной перечислением, но
    отдельная проверка нужна там, где роль приходит из внешнего провайдера.
    """
    if role not in tuple(TenantRole):
        raise InvariantViolationError(f"Неизвестная роль: {role}")
