class ApplicationError(Exception):
    """Базовая ошибка слоя приложения."""


class PermissionDeniedError(ApplicationError):
    """Операция недоступна текущему пользователю или тенанту."""


class EgressPolicyViolationError(ApplicationError):
    """Попытка отправить код репозитория внешнему провайдеру вопреки политике."""
