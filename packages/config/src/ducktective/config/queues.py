REVIEW_TASK_NAME = "run_review_task"
INDEX_TASK_NAME = "build_index_task"

REVIEW_QUEUE = "arq:queue:review"
INDEX_QUEUE = "arq:queue:index"
"""У каждого воркера своя очередь.

По умолчанию arq кладёт всё в общую, и воркер разбирает подряд любые задачи —
включая чужие, функций для которых у него нет. Пока воркер был один, это
не проявлялось; со вторым индексация начала попадать ревьюеру и падать с
«function not found».
"""
