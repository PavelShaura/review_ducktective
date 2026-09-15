import json
from pathlib import (
    Path,
)

import httpx
from fastapi import (
    FastAPI,
)

from ducktective.api.routers import (
    logs,
)
from ducktective.api.security import (
    authenticated_identity,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.tenancy.value_objects import (
    VerifiedIdentity,
)


ADMIN = VerifiedIdentity(issuer="http://idp", subject="1", email="Admin@Example.com")
MEMBER = VerifiedIdentity(issuer="http://idp", subject="2", email="member@example.com")


def build_app(settings: Settings, identity: VerifiedIdentity) -> FastAPI:
    """Ручка с подменённым входом: провайдер личности здесь не проверяется."""
    app = FastAPI()
    app.include_router(logs.router)
    app.state.settings = settings
    app.dependency_overrides[authenticated_identity] = lambda: identity
    return app


def settings_with(log_file: Path | None, admins: str = "admin@example.com") -> Settings:
    return Settings(
        _env_file=None,
        app_log_file=log_file,
        installation_admin_emails=admins,
    )


async def _get(app: FastAPI, url: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url)


async def test_member_of_organization_is_not_enough(tmp_path: Path) -> None:
    """Журнал общий для всех организаций: право даёт только список установки."""
    app = build_app(settings_with(tmp_path / "log.jsonl"), MEMBER)

    response = await _get(app, "/admin/logs")

    assert response.status_code == 403


async def test_admin_email_is_matched_case_insensitively(tmp_path: Path) -> None:
    """Провайдер отдаёт почту как записал пользователь; список — как записал оператор."""
    log_file = tmp_path / "log.jsonl"
    log_file.write_text(
        json.dumps({"event": "api.started", "level": "info", "logger": "ducktective.api"}) + "\n",
        encoding="utf-8",
    )
    app = build_app(settings_with(log_file, admins=" ADMIN@example.com , other@x "), ADMIN)

    response = await _get(app, "/admin/logs?level=info&logger=ducktective&q=started")

    assert response.status_code == 200
    payload = response.json()
    assert payload["file"] == str(log_file)
    assert payload["skipped_lines"] == 0
    assert payload["records"] == [
        {
            "timestamp": None,
            "level": "info",
            "logger": "ducktective.api",
            "event": "api.started",
            "exception": None,
            "fields": {},
        }
    ]


async def test_without_log_file_setting_the_reason_is_named(tmp_path: Path) -> None:
    app = build_app(settings_with(None), ADMIN)

    response = await _get(app, "/admin/logs")

    assert response.status_code == 409
    assert "APP_LOG_FILE" in response.json()["detail"]


async def test_missing_file_is_not_an_empty_journal(tmp_path: Path) -> None:
    app = build_app(settings_with(tmp_path / "absent.jsonl"), ADMIN)

    response = await _get(app, "/admin/logs")

    assert response.status_code == 404


async def test_limit_is_bounded(tmp_path: Path) -> None:
    log_file = tmp_path / "log.jsonl"
    log_file.write_text("", encoding="utf-8")
    app = build_app(settings_with(log_file), ADMIN)

    assert (await _get(app, "/admin/logs?limit=0")).status_code == 422
    assert (await _get(app, "/admin/logs?limit=1001")).status_code == 422
    assert (await _get(app, "/admin/logs?level=verbose")).status_code == 422
