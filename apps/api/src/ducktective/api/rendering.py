from rich.console import (
    Console,
)
from rich.panel import (
    Panel,
)
from rich.syntax import (
    Syntax,
)
from rich.table import (
    Table,
)
from rich.text import (
    Text,
)

from ducktective.application.indexing.build_embeddings import (
    EmbeddingOutcome,
)
from ducktective.application.indexing.build_index import (
    IndexOutcome,
)
from ducktective.application.review.run_review import (
    ReviewOutcome,
)
from ducktective.core.review.entities import (
    Finding,
    ReviewRun,
)
from ducktective.core.review.value_objects import (
    ReviewStatus,
    Severity,
)


SEVERITY_ORDER = (
    Severity.CRITICAL,
    Severity.MAJOR,
    Severity.MINOR,
    Severity.NITPICK,
)

SEVERITY_STYLES = {
    Severity.CRITICAL: "bold red",
    Severity.MAJOR: "bold yellow",
    Severity.MINOR: "cyan",
    Severity.NITPICK: "dim",
}

SEVERITY_LABELS = {
    Severity.CRITICAL: "КРИТИЧНО",
    Severity.MAJOR: "ВАЖНО",
    Severity.MINOR: "МЕЛОЧЬ",
    Severity.NITPICK: "ПРИДИРКА",
}

STATUS_STYLES = {
    ReviewStatus.COMPLETED: "green",
    ReviewStatus.FAILED: "red",
    ReviewStatus.CANCELLED: "yellow",
}


def render_index_outcome(
    console: Console,
    outcome: IndexOutcome,
    embeddings: EmbeddingOutcome | None = None,
    *,
    elapsed_seconds: float,
) -> None:
    """Показывает итог индексации.

    Переиспользованные файлы выводятся отдельной строкой: на них держится
    обещание про быстрый инкремент, и видеть их число важнее, чем общее.
    """
    stats = outcome.stats
    kind = "инкрементальная" if outcome.is_incremental else "полная"

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("ревизия", outcome.snapshot.commit_sha[:12])
    table.add_row("индексация", f"{kind}, {elapsed_seconds:.2f} с")
    table.add_row("файлов", str(stats.files_total))
    table.add_row("разобрано", str(stats.files_parsed))
    table.add_row("не менялось", f"[green]{stats.files_reused}[/]")
    if stats.files_deleted:
        table.add_row("исчезло", str(stats.files_deleted))
    table.add_row("символов", str(stats.symbols))
    table.add_row("чанков", str(stats.chunks))
    if stats.edges:
        table.add_row("связей", f"{stats.edges}, из них разрешено {stats.edges_resolved}")

    if embeddings is not None:
        table.add_row(
            "векторы",
            f"{embeddings.total} ({embeddings.computed} посчитано, "
            f"{embeddings.reused} переиспользовано)",
        )

    console.print(Panel(table, title="индекс", border_style="cyan", padding=(1, 2)))

    if outcome.unreadable:
        console.print(
            f"[yellow]Не удалось прочитать файлов: {len(outcome.unreadable)}[/] "
            f"[dim]({', '.join(outcome.unreadable[:3])}…)[/]"
        )


def render_outcome_notes(console: Console, outcome: ReviewOutcome) -> None:
    """Показывает, что модель предложила и что было отброшено.

    Без этого «замечаний нет» скрывает разницу между молчанием модели
    и отбраковкой всех её ответов.
    """
    if outcome.proposed == 0 and not outcome.failed_files and not outcome.files_with_context:
        return

    parts: list[str] = []
    if outcome.files_with_context:
        parts.append(f"с контекстом из индекса {outcome.files_with_context}")
    parts.append(f"модель предложила {outcome.proposed}")
    if outcome.discarded_outside_diff:
        parts.append(f"вне диффа {outcome.discarded_outside_diff}")
    if outcome.discarded_without_evidence:
        parts.append(f"без цитаты {outcome.discarded_without_evidence}")
    if outcome.discarded_as_duplicate:
        parts.append(f"повторов {outcome.discarded_as_duplicate}")
    if outcome.failed_files:
        parts.append(f"файлов с ошибкой {len(outcome.failed_files)}")

    console.print()
    console.print(f"[dim]{' · '.join(parts)}[/]")

    for failure in outcome.failed_files:
        console.print(f"[yellow]  {failure}[/]")


def render_markdown(run: ReviewRun) -> str:
    """Отчёт для вставки в описание pull request."""
    lines = [
        f"## Ревью {run.base_sha[:8]} → {run.head_sha[:8]}",
        "",
        f"Файлов: {len(run.files)} · находок: {len(run.findings)} · "
        f"токенов: {run.tokens_input} → {run.tokens_output}",
    ]

    if not run.findings:
        lines.extend(["", "Замечаний нет."])
        return "\n".join(lines)

    for severity in SEVERITY_ORDER:
        findings = [finding for finding in run.findings if finding.severity is severity]
        if not findings:
            continue

        lines.extend(["", f"### {SEVERITY_LABELS[severity]} ({len(findings)})"])
        for finding in findings:
            lines.extend(
                [
                    "",
                    f"**{finding.title}**  ",
                    f"`{finding.file_path}:{finding.line_start}` · {finding.category.value}",
                    "",
                    finding.body_markdown.strip(),
                ]
            )
            if finding.suggested_patch:
                lines.extend(["", "```python", finding.suggested_patch.strip(), "```"])

    return "\n".join(lines)


def render_run(console: Console, run: ReviewRun) -> None:
    console.print()
    console.print(_build_summary(run))

    if run.failure_reason:
        console.print(
            Panel(run.failure_reason, title="Прогон завершился с ошибкой", border_style="red")
        )
        return

    if not run.findings:
        console.print(
            Panel(
                "Замечаний нет — модель не нашла проблем в изменённых строках.",
                border_style="green",
            )
        )
        return

    for severity in SEVERITY_ORDER:
        findings = [finding for finding in run.findings if finding.severity is severity]
        if not findings:
            continue

        console.print()
        console.rule(
            f"[{SEVERITY_STYLES[severity]}]{SEVERITY_LABELS[severity]}[/] · {len(findings)}",
            style=SEVERITY_STYLES[severity],
        )
        for finding in findings:
            console.print(_build_finding_panel(finding))


def _build_summary(run: ReviewRun) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()

    status_style = STATUS_STYLES.get(run.status, "white")
    table.add_row("Прогон", str(run.id))
    table.add_row("Статус", Text(run.status.value, style=status_style))
    table.add_row("Ревизии", f"{run.base_sha[:8]} → {run.head_sha[:8]}")
    table.add_row("Файлов", str(len(run.files)))
    table.add_row("Находок", _format_totals(run))
    table.add_row("Токены", f"{run.tokens_input} → {run.tokens_output}")
    if run.cost_usd:
        table.add_row("Стоимость", f"${run.cost_usd:.4f}")

    return Panel(table, title="Ревью", border_style="blue", expand=False)


def _format_totals(run: ReviewRun) -> Text:
    totals = run.severity_totals
    if not totals:
        return Text("0", style="green")

    parts = Text()
    for severity in SEVERITY_ORDER:
        count = totals.get(severity.value, 0)
        if not count:
            continue
        if parts:
            parts.append("  ")
        parts.append(f"{SEVERITY_LABELS[severity]}: {count}", style=SEVERITY_STYLES[severity])
    return parts


def _build_finding_panel(finding: Finding) -> Panel:
    body = Text()
    body.append(finding.body_markdown.strip())

    if finding.confidence is not None:
        body.append(f"\n\nУверенность модели: {finding.confidence:.0%}", style="dim")

    if finding.evidence:
        body.append("\n\nОснование:\n", style="dim")
        for item in finding.evidence:
            body.append(f"  {item.snippet.strip()}\n", style="italic dim")

    content: Text | Table = body
    if finding.suggested_patch:
        content = Table.grid()
        content.add_row(body)
        content.add_row(
            Syntax(
                finding.suggested_patch,
                "python",
                theme="ansi_dark",
                background_color="default",
                word_wrap=True,
            )
        )

    location = f"{finding.file_path}:{finding.line_start}"
    if finding.line_end != finding.line_start:
        location = f"{finding.file_path}:{finding.line_start}-{finding.line_end}"

    return Panel(
        content,
        title=f"[{SEVERITY_STYLES[finding.severity]}]{finding.title}[/]",
        subtitle=f"[dim]{location} · {finding.category.value}[/]",
        subtitle_align="left",
        border_style=SEVERITY_STYLES[finding.severity],
        padding=(1, 2),
    )
