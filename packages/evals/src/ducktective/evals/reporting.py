from rich.console import (
    Console,
)
from rich.table import (
    Table,
)

from ducktective.evals.harness import (
    EvaluationOutcome,
)


def render_evaluation(console: Console, outcome: EvaluationOutcome) -> None:
    metrics = outcome.metrics

    table = Table(title=f"eval · {outcome.label}", title_style="bold")
    table.add_column("случай")
    table.add_column("ожидание")
    table.add_column("итог")
    table.add_column("находок", justify="right")

    for item in outcome.outcomes:
        expected = "чисто" if item.case.is_clean else "дефект"
        if item.failure:
            verdict = "[red]ошибка[/]"
        elif item.case.is_clean:
            verdict = "[red]ложная тревога[/]" if item.findings else "[green]молчит[/]"
        else:
            verdict = "[green]найден[/]" if item.found_expected else "[yellow]пропущен[/]"

        table.add_row(item.case.name, expected, verdict, str(len(item.findings)))

    console.print(table)

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    if len(outcome.attempts) > 1:
        low, high = outcome.recall_spread
        summary.add_row(
            "recall по внесённым дефектам",
            f"в среднем {outcome.mean_recall:.0%}  "
            f"(разброс {low:.0%}–{high:.0%} по {len(outcome.attempts)} прогонам)",
        )
    else:
        summary.add_row(
            "recall по внесённым дефектам",
            f"{metrics.recall:.0%}  ({metrics.found}/{metrics.defects})",
        )
    summary.add_row(
        "ложные тревоги на чистых",
        f"{metrics.false_alarm_rate:.0%}  ({metrics.clean_with_findings}/{metrics.clean_cases})",
    )
    summary.add_row("уровень назван верно", f"{metrics.severity_accuracy:.0%}")
    summary.add_row("категория названа верно", f"{metrics.category_accuracy:.0%}")
    summary.add_row("находок всего", str(metrics.findings_total))
    summary.add_row(
        "случаев с контекстом",
        f"{metrics.cases_with_context}/{metrics.cases}"
        + ("  [yellow]контекст не собрался[/]" if not metrics.cases_with_context else ""),
    )
    if metrics.failures:
        summary.add_row("случаев с ошибкой", f"[red]{metrics.failures}[/]")

    console.print(summary)

    for item in outcome.outcomes:
        if item.failure:
            console.print(f"[red]  {item.case.name}:[/] {item.failure}")
