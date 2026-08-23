from cryptography.fernet import (
    Fernet,
    InvalidToken,
)

from ducktective.core.exceptions import (
    SecretNotDecryptableError,
)


class FernetSecretCipher:
    """Шифрование ключей провайдеров симметричным секретом из окружения.

    Секрет живёт вне базы — в этом вся разница между зашифрованной строкой
    и открытой: выгрузка, резервная копия и чужой доступ к тому не дают
    ничего, пока секрет не утёк вместе с ними.
    """

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(secret_key.encode("utf-8"))

    def encrypt(self, secret: str) -> str:
        return self._fernet.encrypt(secret.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as error:
            raise SecretNotDecryptableError(
                "Ключ провайдера не расшифровывается: сменился MODELS_SECRET_KEY. "
                "Введите ключи моделей заново"
            ) from error


def generate_secret_key() -> str:
    """Новый секрет шифрования. Печатается командой, а не создаётся молча.

    Секрет, сгенерированный приложением при первом запуске, переживает
    ровно до первой пересборки контейнера, после чего все сохранённые
    ключи становятся мусором без объяснения причины.
    """
    return Fernet.generate_key().decode("utf-8")
