import os
from pathlib import (
    Path,
)

import pytest

from ducktective.mcp_server.__main__ import (
    ENV_FILE_VARIABLE,
    load_settings,
)


ENV_CONTENTS = """
DATABASE_URL=postgresql+asyncpg://user:secret@elsewhere:5432/ducktective
MCP_TENANT_ID=11111111-1111-1111-1111-111111111111
LOCAL_EMBEDDING_BASE_URL=http://models.local:1234/v1
"""


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отвязывает окружение процесса от теста.

    Файл настроек переносится в `os.environ`, и без подмены самого отображения
    прочитанное осталось бы в процессе до конца прогона.
    """
    monkeypatch.setattr(os, "environ", dict(os.environ))


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "project.env"
    path.write_text(ENV_CONTENTS, encoding="utf-8")
    return path


def test_settings_are_read_from_the_named_file(env_file: Path) -> None:
    """Рабочий каталог у сервера чужой: клиент запускает его из своего."""
    settings = load_settings(str(env_file))

    assert settings.require_database_url().endswith("@elsewhere:5432/ducktective")
    assert settings.mcp_tenant_id == "11111111-1111-1111-1111-111111111111"
    assert settings.local_embedding_base_url == "http://models.local:1234/v1"


def test_named_file_wins_over_the_environment(env_file: Path) -> None:
    """`litellm` при импорте сам грузит `.env` из текущего каталога в окружение."""
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:secret@случайно-рядом:5432/other"

    assert (
        load_settings(str(env_file)).require_database_url().endswith("@elsewhere:5432/ducktective")
    )


def test_variable_is_used_when_the_flag_is_absent(env_file: Path) -> None:
    os.environ[ENV_FILE_VARIABLE] = str(env_file)

    assert load_settings(None).mcp_tenant_id == "11111111-1111-1111-1111-111111111111"


def test_flag_wins_over_the_variable(env_file: Path) -> None:
    other = env_file.parent / "other.env"
    other.write_text("MCP_TENANT_ID=22222222-2222-2222-2222-222222222222\n", encoding="utf-8")
    os.environ[ENV_FILE_VARIABLE] = str(env_file)

    assert load_settings(str(other)).mcp_tenant_id == "22222222-2222-2222-2222-222222222222"


def test_missing_file_stops_the_server_with_the_reason(tmp_path: Path) -> None:
    """Иначе клиент показал бы «сервер не поднялся» без причины."""
    missing = tmp_path / "нет-такого.env"

    with pytest.raises(SystemExit) as error:
        load_settings(str(missing))

    assert str(missing) in str(error.value)
