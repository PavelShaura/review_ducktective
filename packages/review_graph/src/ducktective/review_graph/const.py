BUILD_CONTEXT_NODE = "build_context"
PLAN_REVIEW_NODE = "plan_review"
REVIEW_NODE = "review"
AGGREGATE_NODE = "aggregate"
VERIFY_NODE = "verify"

DEFAULT_MAX_CONCURRENT_REVIEWS = 1
"""Один файл за раз.

Локальная модель обслуживает запросы по очереди, и параллельный запуск узлов
не ускоряет прогон, а только отбирает у него окно контекста. Значение поднимают
там, где за роутером стоит несколько моделей.
"""
