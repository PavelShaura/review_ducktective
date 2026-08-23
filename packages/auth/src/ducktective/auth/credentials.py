import json
from dataclasses import (
    dataclass,
)
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from pathlib import (
    Path,
)


DEFAULT_LOCATION = Path.home() / ".config" / "ducktective" / "credentials.json"
EXPIRY_MARGIN_SECONDS = 30


@dataclass(frozen=True, kw_only=True)
class StoredCredentials:
    """Сохранённый вход терминала.

    Токен доступа живёт минуты, поэтому рядом лежит обновляющий: иначе
    каждая команда требовала бы браузера. Файл пишется правами `600` —
    в нём лежит ровно то, чем входят.
    """

    issuer: str
    access_token: str
    refresh_token: str
    expires_at: datetime

    def is_fresh(self, *, at: datetime | None = None) -> bool:
        moment = at or datetime.now(UTC)
        return moment + timedelta(seconds=EXPIRY_MARGIN_SECONDS) < self.expires_at


def load_credentials(location: Path = DEFAULT_LOCATION) -> StoredCredentials | None:
    if not location.exists():
        return None

    try:
        payload = json.loads(location.read_text(encoding="utf-8"))
        return StoredCredentials(
            issuer=str(payload["issuer"]),
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        )
    except (ValueError, KeyError, OSError):
        return None


def save_credentials(
    credentials: StoredCredentials,
    location: Path = DEFAULT_LOCATION,
) -> None:
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(
        json.dumps(
            {
                "issuer": credentials.issuer,
                "access_token": credentials.access_token,
                "refresh_token": credentials.refresh_token,
                "expires_at": credentials.expires_at.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    location.chmod(0o600)


def forget_credentials(location: Path = DEFAULT_LOCATION) -> bool:
    if not location.exists():
        return False
    location.unlink()
    return True
