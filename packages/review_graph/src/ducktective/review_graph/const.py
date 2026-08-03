"""Имена узлов графа и степень параллелизма.

Имена берутся у домена, а не пишутся заново: отметка о деградации называет
этап конвейера, и разойтись имени узла в логе с именем этапа в отметке негде.
"""

from ducktective.core.review.degradation import (
    ReviewStage,
)


BUILD_CONTEXT_NODE = ReviewStage.BUILD_CONTEXT.value
PLAN_REVIEW_NODE = ReviewStage.PLAN_REVIEW.value
REVIEW_NODE = ReviewStage.REVIEW.value
AGGREGATE_NODE = ReviewStage.AGGREGATE.value
VERIFY_NODE = ReviewStage.VERIFY.value

DEFAULT_MAX_CONCURRENT_REVIEWS = 1
"""Один файл за раз.

Локальная модель обслуживает запросы по очереди, и параллельный запуск узлов
не ускоряет прогон, а только отбирает у него окно контекста. Значение поднимают
там, где за роутером стоит несколько моделей.
"""
