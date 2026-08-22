from ducktective.core.indexing.ports import (
    SymbolReference,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)


SAMPLE = """
import json
from decimal import Decimal
from app.storage import Repository as Store


class BaseBuilder:
    pass


class ReportBuilder(BaseBuilder):
    @property
    def rate(self) -> Decimal:
        return Decimal("0.2")

    def build(self, student_id):
        store = Store()
        data = store.fetch(student_id)
        if not data:
            raise ValueError("нет данных")
        return json.dumps(self.normalize(data))

    def normalize(self, data):
        return len(data)
"""


def references_of(content: str = SAMPLE, path: str = "app/report.py") -> list[SymbolReference]:
    return PythonParser().parse(path=path, content=content).references


def targets(source_name: str, content: str = SAMPLE) -> set[tuple[str, EdgeKind]]:
    parsed = PythonParser().parse(path="app/report.py", content=content)
    by_id = {symbol.id: symbol.qualified_name for symbol in parsed.symbols}
    return {
        (str(reference.target_name), reference.kind)
        for reference in parsed.references
        if by_id[reference.source_symbol_id] == source_name
    }


def test_base_class_becomes_an_edge() -> None:
    assert ("app.report.BaseBuilder", EdgeKind.INHERITS) in targets("app.report.ReportBuilder")


def test_imported_name_is_expanded_to_its_module() -> None:
    """`Decimal` в коде — это `decimal.Decimal` в графе."""
    assert ("decimal.Decimal", EdgeKind.CALLS) in targets("app.report.ReportBuilder.rate")


def test_aliased_import_keeps_the_original_name() -> None:
    assert ("app.storage.Repository", EdgeKind.CALLS) in targets("app.report.ReportBuilder.build")


def test_self_call_resolves_to_the_owning_class() -> None:
    """Соседний метод — это связь, отвечающая на вопрос «что сломается»."""
    assert ("app.report.ReportBuilder.normalize", EdgeKind.CALLS) in targets(
        "app.report.ReportBuilder.build"
    )


def test_raise_is_recorded_once() -> None:
    build = targets("app.report.ReportBuilder.build")

    assert ("ValueError", EdgeKind.RAISES) in build
    assert ("ValueError", EdgeKind.CALLS) not in build


def test_decorator_is_recorded() -> None:
    assert ("property", EdgeKind.DECORATES) in targets("app.report.ReportBuilder.rate")


def test_builtins_do_not_pollute_the_graph() -> None:
    normalize = targets("app.report.ReportBuilder.normalize")

    assert not any(name == "len" for name, _ in normalize)


def test_unknown_receiver_keeps_the_written_name() -> None:
    """Тип переменной статически неизвестен — имя сохраняется как есть."""
    build = targets("app.report.ReportBuilder.build")

    assert ("store.fetch", EdgeKind.CALLS) in build


def test_attribute_call_is_less_certain_than_a_direct_one() -> None:
    parsed = PythonParser().parse(path="app/report.py", content=SAMPLE)
    by_target = {str(reference.target_name): reference for reference in parsed.references}

    assert by_target["app.storage.Repository"].confidence == 1.0
    assert by_target["store.fetch"].confidence < 1.0


def test_method_references_do_not_leak_into_the_class() -> None:
    """Класс не присваивает себе то, что делают его методы."""
    class_targets = targets("app.report.ReportBuilder")

    assert ("decimal.Decimal", EdgeKind.CALLS) not in class_targets
    assert ("ValueError", EdgeKind.RAISES) not in class_targets


def test_module_level_call_belongs_to_the_module() -> None:
    module = targets("app.report", "import json\n\nCONFIG = json.loads('{}')\n")

    assert ("json.loads", EdgeKind.CALLS) in module


def test_file_without_references_yields_none() -> None:
    assert references_of("VALUE = 1\n") == []
