from ducktective.api.dev import (
    plan,
)


def names(**flags: bool) -> list[str]:
    return [service.name for service in plan(**flags)]


def test_everything_is_started_by_default() -> None:
    assert names(with_web=True, with_workers=True) == ["api", "indexer", "reviewer", "web"]


def test_web_can_be_left_out() -> None:
    assert "web" not in names(with_web=False, with_workers=True)


def test_workers_can_be_left_out() -> None:
    started = names(with_web=False, with_workers=False)

    assert started == ["api"]


def test_workers_stay_separate_processes() -> None:
    """Разделение по профилю нагрузки закреплено решением D-013.

    Удобство запуска не повод его пересматривать: супервизор порождает те же
    процессы, что и запуск руками, а не втягивает воркеры в процесс API.
    """
    services = {service.name: service for service in plan(with_web=False, with_workers=True)}

    assert services["indexer"].command != services["reviewer"].command
    assert all(
        service.command != services["api"].command
        for service in services.values()
        if service.name != "api"
    )


def test_every_service_says_where_to_look() -> None:
    """Адреса названы до первой строки логов, иначе их ищут в чужом выводе."""
    assert all(
        service.address and service.role for service in plan(with_web=True, with_workers=True)
    )


def test_web_is_started_in_its_own_directory() -> None:
    web = next(
        service for service in plan(with_web=True, with_workers=False) if service.name == "web"
    )

    assert web.cwd is not None
    assert (web.cwd / "package.json").is_file()


def test_reload_is_off_unless_asked() -> None:
    api = next(service for service in plan(with_web=False, with_workers=False))

    assert "--reload" not in api.command


def test_reload_reaches_the_api_command() -> None:
    """Перезапуск нужен только API: воркеры перечитывают код при следующей задаче."""
    services = plan(with_web=False, with_workers=True, reload=True)
    api = next(service for service in services if service.name == "api")

    assert "--reload" in api.command
    assert all("--reload" not in service.command for service in services if service.name != "api")
