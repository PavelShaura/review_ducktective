from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)


class CancelReviewRun(TransactionalUseCase):
    """Просит прекратить идущее расследование.

    Прогон не обрывается на месте: он помечается отменённым, а воркер видит
    это перед следующим файлом и выходит. Файл, который модель читает прямо
    сейчас, дочитывается — прерывать запрос к модели на середине незачем,
    результат всё равно не сохранится.

    Вместе с прогоном отменяется и сборка индекса на его ревизии, если она
    ещё не закончена: её поставил сам запуск дела, и без дела она только
    занимает воркер — следующая сборка в очереди ждала бы её полчаса
    ради индекса, который никому не нужен. Готовый снапшот не трогается,
    как и сборка на другой ревизии.
    """

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> bool:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if run.is_finished:
                return False

            run.cancel()

            snapshot = await self._unit_of_work.index_snapshots.find_latest(run.repository_id)
            if (
                snapshot is not None
                and not snapshot.is_finished
                and snapshot.commit_sha == run.head_sha
            ):
                snapshot.cancel()

            await self._commit_and_publish()
            return True
