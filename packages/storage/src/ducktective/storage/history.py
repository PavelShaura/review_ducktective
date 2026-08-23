"""Чтение того, что уже находили в файле и как это оценил человек.

Не репозиторий агрегата: читается срез по нескольким прогонам сразу, и
собирать ради него `ReviewRun` целиком значило бы поднимать из базы все
находки всех прогонов, чтобы показать пять.
"""

from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.review.ports import (
    PastFinding,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.storage.models.review import (
    FindingFeedbackModel,
    FindingModel,
    ReviewRunModel,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
)


class PostgresFindingHistory:
    """История отметок, живущая на своей сессии.

    Сессия открывается на запрос, а не берётся у прогона: инструмент
    спрашивают посреди работы модели, то есть заведомо вне транзакции
    ревью, и держать ради этого чужую сессию открытой незачем.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: TenantId | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id

    async def for_file(
        self,
        repository_id: RepositoryId,
        path: str,
        *,
        limit: int = 5,
    ) -> list[PastFinding]:
        """Размеченные находки файла, свежая отметка каждой находки.

        Мнение можно менять, и решением считается свежее — то же правило,
        по которому сводка отметок берёт последний вердикт.
        """
        latest = (
            select(
                FindingFeedbackModel.finding_id,
                FindingFeedbackModel.verdict,
                FindingFeedbackModel.comment,
                FindingFeedbackModel.created_at,
            )
            .distinct(FindingFeedbackModel.finding_id)
            .order_by(
                FindingFeedbackModel.finding_id,
                FindingFeedbackModel.created_at.desc(),
            )
            .subquery()
        )
        statement = (
            select(
                FindingModel.title,
                FindingModel.severity,
                FindingModel.line_start,
                latest.c.verdict,
                latest.c.comment,
            )
            .join(ReviewRunModel, ReviewRunModel.id == FindingModel.run_id)
            .join(latest, latest.c.finding_id == FindingModel.id)
            .where(
                ReviewRunModel.repository_id == repository_id,
                FindingModel.file_path == path,
            )
            .order_by(latest.c.created_at.desc())
            .limit(limit)
        )

        async with self._session_factory() as session:
            await bind_tenant(session, self._tenant_id)
            rows = (await session.execute(statement)).all()

        return [
            PastFinding(
                title=row.title,
                severity=row.severity,
                verdict=row.verdict,
                line_start=row.line_start,
                comment=row.comment,
            )
            for row in rows
        ]
