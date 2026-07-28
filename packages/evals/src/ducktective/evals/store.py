import hashlib
from uuid import (
    uuid4,
)

from sqlalchemy import (
    insert,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.evals.cases import (
    EvalDataset,
)
from ducktective.evals.harness import (
    EvaluationOutcome,
)
from ducktective.storage.models.evals import (
    EvalCaseModel,
    EvalDatasetModel,
    EvalResultModel,
    EvalRunModel,
    PromptVersionModel,
)


class SqlAlchemyEvalStore:
    """Запись прогонов оценки.

    Прогон бесполезен сам по себе — он нужен, чтобы через месяц сравнить
    с ним следующий. Поэтому вместе с метриками сохраняются версия промпта,
    модель и конфигурация: без них цифра не значит ничего.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        dataset: EvalDataset,
        outcome: EvaluationOutcome,
        *,
        model: str,
        prompt: str,
        prompt_name: str,
    ) -> None:
        dataset_id = await self._ensure_dataset(dataset)
        case_ids = await self._ensure_cases(dataset_id, dataset)
        prompt_version_id = await self._ensure_prompt(prompt_name, prompt)

        run_id = uuid4()
        await self._session.execute(
            insert(EvalRunModel).values(
                id=run_id,
                dataset_id=dataset_id,
                prompt_version_id=prompt_version_id,
                label=outcome.label,
                model=model,
                config={"cases": outcome.metrics.cases},
                metrics=outcome.metrics.as_dict(),
            )
        )

        rows = [
            {
                "id": uuid4(),
                "eval_run_id": run_id,
                "eval_case_id": case_ids[item.case.name],
                "found_expected": item.found_expected,
                "findings_total": len(item.findings),
                "raw": {
                    "failure": item.failure,
                    "findings": [
                        {
                            "title": finding.title,
                            "severity": finding.severity.value,
                            "category": finding.category.value,
                        }
                        for finding in item.findings
                    ],
                },
            }
            for item in outcome.outcomes
        ]
        if rows:
            await self._session.execute(insert(EvalResultModel), rows)

    async def _ensure_dataset(self, dataset: EvalDataset) -> object:
        existing = (
            await self._session.execute(
                select(EvalDatasetModel.id).where(EvalDatasetModel.name == dataset.name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        dataset_id = uuid4()
        await self._session.execute(
            insert(EvalDatasetModel).values(
                id=dataset_id,
                name=dataset.name,
                description=dataset.description,
            )
        )
        return dataset_id

    async def _ensure_cases(self, dataset_id: object, dataset: EvalDataset) -> dict[str, object]:
        known = {
            name: case_id
            for case_id, name in (
                await self._session.execute(
                    select(EvalCaseModel.id, EvalCaseModel.name).where(
                        EvalCaseModel.dataset_id == dataset_id
                    )
                )
            ).all()
        }

        for case in dataset.cases:
            if case.name in known:
                continue

            case_id = uuid4()
            await self._session.execute(
                insert(EvalCaseModel).values(
                    id=case_id,
                    dataset_id=dataset_id,
                    name=case.name,
                    file_path=case.file_path,
                    patch=case.patch,
                    expected={
                        "category": (
                            case.expectation.category.value if case.expectation.category else None
                        ),
                        "min_severity": (
                            case.expectation.min_severity.value
                            if case.expectation.min_severity
                            else None
                        ),
                        "keywords": list(case.expectation.keywords),
                    },
                    tags=list(case.tags),
                )
            )
            known[case.name] = case_id

        return known

    async def _ensure_prompt(self, name: str, template: str) -> object:
        content_hash = hashlib.sha256(template.encode("utf-8")).hexdigest()
        existing = (
            await self._session.execute(
                select(PromptVersionModel.id).where(
                    PromptVersionModel.name == name,
                    PromptVersionModel.content_hash == content_hash,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        prompt_id = uuid4()
        await self._session.execute(
            insert(PromptVersionModel).values(
                id=prompt_id,
                name=name,
                content_hash=content_hash,
                template=template,
            )
        )
        return prompt_id
