import asyncio
import os
import signal
import sys
from asyncio.subprocess import (
    Process,
)
from collections.abc import (
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from pathlib import (
    Path,
)

from rich.console import (
    Console,
)
from rich.rule import (
    Rule,
)
from rich.table import (
    Table,
)
from rich.text import (
    Text,
)

from ducktective.config.queues import (
    INDEX_QUEUE,
    REVIEW_QUEUE,
)


SHUTDOWN_GRACE_SECONDS = 10.0
"""Сколько ждать добровольного выхода, прежде чем убивать.

Воркер индексации выходит на ближайшей отсечке между пачками файлов,
и на крупном репозитории эта отсечка не мгновенна.
"""

COLOURS = {
    "api": "bright_yellow",
    "web": "bright_cyan",
    "indexer": "bright_green",
    "reviewer": "bright_magenta",
}
"""Цвет закреплён за источником на весь прогон.

Четыре потока логов в одном терминале различаются цветом раньше, чем
прочитано имя, — поэтому цвет держится постоянным, а не выдаётся по порядку
запуска."""


@dataclass
class Service:
    """Процесс под присмотром супервизора."""

    name: str
    command: Sequence[str]
    role: str = ""
    address: str = ""
    cwd: Path | None = None
    process: Process | None = field(default=None, init=False)

    @property
    def is_alive(self) -> bool:
        return self.process is not None and self.process.returncode is None


def plan(*, with_web: bool, with_workers: bool, reload: bool = False) -> list[Service]:
    """Собирает список процессов запуска.

    Процессы остаются теми же, что и при запуске руками, — супервизор их
    только порождает и гасит. Воркеры не втягиваются в процесс API намеренно:
    разделение по профилю нагрузки закреплено решением D-013, и удобство
    запуска не повод его пересматривать.
    """
    serve = [sys.executable, "-m", "ducktective.api.cli", "serve"]
    services = [
        Service(
            name="api",
            command=[*serve, "--reload"] if reload else serve,
            role="REST и WebSocket" + (" · перезапуск по правкам" if reload else ""),
            address="http://127.0.0.1:8000",
        ),
    ]

    if with_workers:
        services += [
            Service(
                name="indexer",
                command=[sys.executable, "-m", "arq", "ducktective.indexer.worker.WorkerSettings"],
                role="разбор кода, граф, векторы",
                address=INDEX_QUEUE,
            ),
            Service(
                name="reviewer",
                command=[
                    sys.executable,
                    "-m",
                    "arq",
                    "ducktective.reviewer.worker.WorkerSettings",
                ],
                role="прогоны ревью",
                address=REVIEW_QUEUE,
            ),
        ]

    if with_web:
        services.append(
            Service(
                name="web",
                command=["npm", "run", "dev"],
                role="интерфейс на Vite",
                address="http://127.0.0.1:5173",
                cwd=_web_directory(),
            )
        )

    return services


def _web_directory() -> Path:
    """Каталог фронта, найденный по корню монорепозитория.

    Ищется маркером, а не отсчётом каталогов вверх: глубина установки
    отличается от глубины исходников, и посчитанный путь ломается молча.
    """
    for candidate in Path(__file__).resolve().parents:
        web = candidate / "apps" / "web" / "package.json"
        if web.is_file():
            return web.parent

    raise SystemExit("Не нашёл apps/web — запустите команду из каталога проекта")


async def supervise(services: list[Service], *, console: Console) -> int:
    """Держит процессы поднятыми до первого падения или Ctrl+C.

    Выход любого из них гасит остальных: половина системы, продолжающая
    работать после падения второй половины, выглядит рабочей и обманывает.

    Вывод сводится в один поток с пометкой источника — иначе разбирать,
    чей это лог, приходится по памяти.
    """
    stopping = asyncio.Event()
    _catch_signals(stopping)

    _announce(services, console=console)
    started = await _start_all(services, console=console)
    if not started:
        return 1

    pumps = [
        asyncio.create_task(_pump(service, console=console))
        for service in services
        if service.is_alive
    ]
    finished = asyncio.create_task(_first_exit(services))
    interrupted = asyncio.create_task(stopping.wait())

    try:
        await asyncio.wait([finished, interrupted], return_when=asyncio.FIRST_COMPLETED)
        _report(finished, console=console)
    finally:
        await _stop_all(services)
        for task in [*pumps, finished, interrupted]:
            task.cancel()

    _say(console, Text("всё остановлено", style="dim"))
    return 0 if stopping.is_set() else 1


def _report(finished: "asyncio.Task[Service]", *, console: Console) -> None:
    if finished.done():
        service = finished.result()
        _say(console, Rule(f"[bright_red]{service.name} завершился[/]", style="bright_red"))
        return

    _say(console, Rule("[dim]останавливаю[/]", style="grey42"))


def _say(console: Console, renderable: object) -> None:
    """Печатает, не роняя супервизор об закрытый вывод.

    Дети живут в собственных сессиях, и Ctrl+C с терминала до них не доходит —
    снять их может только супервизор. Значит, он обязан дожить до уборки:
    оборванная труба (`… | head`) не должна оставлять воркеры сиротами.
    """
    try:
        console.print(renderable)
    except (BrokenPipeError, OSError):
        return


async def _start_all(services: list[Service], *, console: Console) -> bool:
    for service in services:
        try:
            service.process = await asyncio.create_subprocess_exec(
                *service.command,
                cwd=service.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except (OSError, FileNotFoundError) as error:
            console.print(f"[red]{service.name} не запустился: {error}[/]")
            await _stop_all(services)
            return False

    return True


def _announce(services: list[Service], *, console: Console) -> None:
    """Показывает, что поднимается и куда идти смотреть.

    Адреса названы до первой строки логов: искать их в чужом выводе,
    когда он уже поехал в четыре потока, неудобно.
    """
    table = Table(box=None, show_header=False, padding=(0, 3, 0, 0))
    table.add_column(justify="right")
    table.add_column()
    table.add_column(style="dim")

    for service in services:
        table.add_row(
            Text(service.name, style=f"bold {_colour(service.name)}"),
            Text(service.address, style="underline" if "://" in service.address else "dim"),
            Text(service.role),
        )

    console.print()
    console.print(table)
    console.print(Rule(style="grey42"))


async def _pump(service: Service, *, console: Console) -> None:
    """Переливает вывод процесса в общий поток с пометкой источника.

    Цвета исходного процесса разбираются, а не печатаются как есть: structlog
    и uvicorn раскрашивают свой вывод сами, и без разбора управляющие
    последовательности сыплются в терминал видимым мусором.

    Строка кладётся в сетку, чтобы перенос длинного сообщения уходил под
    сообщение, а не в нулевую колонку: иначе выравнивание, ради которого
    метка и фиксирована по ширине, теряется на первой же длинной строке.
    """
    stream = service.process.stdout if service.process else None
    if stream is None:
        return

    while True:
        line = await stream.readline()
        if not line:
            return

        row = Table.grid(padding=0)
        row.add_column(width=TAG_WIDTH + 3, no_wrap=True)
        row.add_column(overflow="fold")
        row.add_row(
            _tag(service.name), Text.from_ansi(line.decode("utf-8", errors="replace").rstrip())
        )
        console.print(row)


async def _first_exit(services: list[Service]) -> Service:
    while True:
        for service in services:
            if service.process is not None and service.process.returncode is not None:
                return service
        await asyncio.sleep(0.2)


async def _stop_all(services: list[Service]) -> None:
    """Просит процессы выйти, а несогласных снимает силой.

    Сигнал уходит всей группе, а не одному процессу: uvicorn в режиме
    перезапуска держит сервер отдельным потомком, `npm run dev` — vite,
    и остановленный родитель оставил бы их жить с занятым портом.
    """
    for service in services:
        _signal_group(service, signal.SIGTERM)

    for service in services:
        if service.process is None:
            continue
        try:
            await asyncio.wait_for(service.process.wait(), timeout=SHUTDOWN_GRACE_SECONDS)
        except TimeoutError:
            _signal_group(service, signal.SIGKILL)
            await service.process.wait()


def _signal_group(service: Service, received: signal.Signals) -> None:
    if not service.is_alive or service.process is None:
        return

    try:
        os.killpg(os.getpgid(service.process.pid), received)
    except ProcessLookupError:
        return


def _catch_signals(stopping: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for received in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(received, stopping.set)


TAG_WIDTH = 10


def _tag(name: str) -> Text:
    """Помечает строку источником.

    Собирается объектом, а не разметкой в строке: в чужом выводе встречаются
    квадратные скобки, и rich принял бы их за собственные теги.

    Ширина фиксирована, чтобы сообщения выстроились в колонку: неровный левый
    край четырёх перемешанных потоков читается заметно хуже.
    """
    return Text(f"{name:>{TAG_WIDTH}} │ ", style=_colour(name))


def _colour(name: str) -> str:
    return COLOURS.get(name, "white")
