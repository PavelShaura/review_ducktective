import argparse
import asyncio
import os
import sys
from pathlib import (
    Path,
)

from dotenv import (
    load_dotenv,
)

from ducktective.config.settings import (
    Settings,
)
from ducktective.mcp_server.runtime import (
    build_runtime,
    resolve_tenant,
)
from ducktective.mcp_server.server import (
    build_server,
)
from ducktective.observability.logging import (
    configure_logging,
)


ENV_FILE_VARIABLE = "DUCKTECTIVE_ENV_FILE"


def main() -> None:
    """Точка входа сервера.

    Логи уходят в stderr при любом транспорте: при stdio stdout занят
    протоколом, а расхождение вывода между транспортами стоило бы дороже
    единообразия.
    """
    arguments = _parse_arguments()
    settings = load_settings(arguments.env_file)
    configure_logging(
        level=settings.app_log_level,
        json_output=settings.app_env != "dev",
        stream=sys.stderr,
    )

    asyncio.run(_serve(settings, arguments))


def load_settings(env_file: str | None) -> Settings:
    """Читает настройки из указанного файла, а не из текущего каталога.

    Сервер по stdio запускает клиент, и рабочим каталогом оказывается его
    собственный, а не каталог проекта. `Settings` ищет `.env` относительно
    текущего каталога, поэтому без явного пути настройки не находятся вовсе,
    и всё приходится перечислять переменными окружения у клиента.

    Файл переносится в окружение с перекрытием, а не передаётся в `Settings`
    аргументом: `litellm` при импорте сам вызывает `load_dotenv`, и `.env`
    из текущего каталога оказывается в `os.environ` раньше нас. Переменная
    окружения старше любого файла настроек, поэтому названный файл иначе
    молча проигрывал бы случайно оказавшемуся рядом.

    Молчаливое падение на несуществующем файле здесь особенно дорого: клиент
    показал бы «сервер не поднялся» без причины.
    """
    reference = env_file or os.environ.get(ENV_FILE_VARIABLE)
    if reference is None:
        return Settings()

    path = Path(reference).expanduser()
    if not path.is_file():
        raise SystemExit(f"Файл настроек не найден: {path}")

    load_dotenv(path, override=True)
    return Settings()


async def _serve(settings: Settings, arguments: argparse.Namespace) -> None:
    """Поднимает сервер поверх зависимостей, созданных в его цикле событий.

    Асинхронные варианты запуска нужны именно поэтому: синхронный `run` завёл бы
    собственный цикл, и пул соединений оказался бы привязан к чужому.
    """
    tenant_id = await resolve_tenant(settings)

    async with build_runtime(settings, tenant_id) as runtime:
        server = build_server(runtime)
        if arguments.transport == "stdio":
            await server.run_stdio_async()
            return

        await server.run_streamable_http_async(
            host=arguments.host or settings.mcp_http_host,
            port=arguments.port or settings.mcp_http_port,
        )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ducktective-mcp",
        description="MCP-сервер навигации по проиндексированной кодовой базе",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio — клиент поднимает сервер сам; http — сервер живёт отдельно",
    )
    parser.add_argument(
        "--env-file",
        help=(
            f"Путь к .env проекта, иначе {ENV_FILE_VARIABLE}. "
            "Без него настройки ищутся в каталоге, из которого запущен клиент"
        ),
    )
    parser.add_argument("--host", help="Адрес для http-транспорта")
    parser.add_argument("--port", type=int, help="Порт для http-транспорта")
    return parser.parse_args()


if __name__ == "__main__":
    main()
