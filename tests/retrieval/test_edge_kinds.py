from uuid import (
    uuid4,
)

from ducktective.core.indexing.value_objects import (
    EdgeKind,
    SymbolKind,
)
from ducktective.core.retrieval.navigation import (
    FragmentRole,
    ReferenceRelation,
)
from ducktective.core.retrieval.ports import (
    CALL_EDGES,
    RelatedSymbol,
    SymbolContext,
)
from ducktective.core.types import (
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)
from ducktective.retrieval.navigation import (
    IndexedCodeNavigator,
)
from tests.fakes import (
    FakeChunkSearch,
    FakeSymbolReader,
)


REPOSITORY_ID = RepositoryId(uuid4())
BASE_CLASS = "BasePack"


def symbol(name: str, *, path: str = "app/packs.py") -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(uuid4()),
        qualified_name=QualifiedName(name),
        kind=SymbolKind.CLASS,
        path=path,
        start_line=10,
        end_line=20,
        signature=f"class {name.rsplit('.', maxsplit=1)[-1]}(BasePack)",
        docstring=None,
        text=f"class {name}: ...",
    )


def related(name: str, kind: EdgeKind) -> RelatedSymbol:
    return RelatedSymbol(context=symbol(name), kind=kind, is_resolved=True)


def build_navigator(reader: FakeSymbolReader) -> IndexedCodeNavigator:
    return IndexedCodeNavigator(REPOSITORY_ID, symbols=reader, search=FakeChunkSearch())


async def test_callers_are_asked_for_calls_only() -> None:
    """Наследник вызывающим не является, и в перечень вызывающих не попадает."""
    reader = FakeSymbolReader(
        by_name={BASE_CLASS: [symbol(BASE_CLASS)]},
        callers=[symbol("app.web.handler")],
    )

    await build_navigator(reader).find_callers(BASE_CLASS)

    assert reader.asked_kinds == [CALL_EDGES]


async def test_filtered_answer_names_the_connections_it_left_out() -> None:
    """Иначе «вызывающих нет» читается как «этот код никому не нужен»."""
    reader = FakeSymbolReader(
        by_name={BASE_CLASS: [symbol(BASE_CLASS)]},
        callers=[],
        kind_counts={EdgeKind.CALLS: 0, EdgeKind.INHERITS: 3, EdgeKind.IMPORTS: 12},
    )

    answer = await build_navigator(reader).find_callers(BASE_CLASS)

    assert answer.is_empty
    assert answer.note is not None
    assert "наследование — 3" in answer.note
    assert "импорт — 12" in answer.note
    assert "find_references" in answer.note


async def test_answer_without_other_connections_stays_silent() -> None:
    """Оговорка появляется, когда есть о чём оговариваться, а не всегда."""
    reader = FakeSymbolReader(
        by_name={BASE_CLASS: [symbol(BASE_CLASS)]},
        callers=[symbol("app.web.handler")],
        kind_counts={EdgeKind.CALLS: 1},
    )

    answer = await build_navigator(reader).find_callers(BASE_CLASS)

    assert answer.note is None


async def test_subclasses_are_asked_for_inheritance() -> None:
    reader = FakeSymbolReader(
        by_name={BASE_CLASS: [symbol(BASE_CLASS)]},
        referring=[
            related("app.packs.BranchPack", EdgeKind.INHERITS),
            related("app.web.views", EdgeKind.IMPORTS),
        ],
    )

    answer = await build_navigator(reader).find_references(
        BASE_CLASS,
        relation=ReferenceRelation.SUBCLASSES,
    )

    assert [fragment.role for fragment in answer.fragments] == [FragmentRole.SUBCLASS]
    assert reader.asked_kinds == [(EdgeKind.INHERITS,)]


async def test_any_relation_labels_every_kind_it_returns() -> None:
    """Разнородный ответ обязан быть подписан: иначе импорт читается как вызов."""
    reader = FakeSymbolReader(
        by_name={BASE_CLASS: [symbol(BASE_CLASS)]},
        referring=[
            related("app.packs.BranchPack", EdgeKind.INHERITS),
            related("app.web.views", EdgeKind.IMPORTS),
            related("app.web.handler", EdgeKind.CALLS),
        ],
    )

    answer = await build_navigator(reader).find_references(BASE_CLASS)

    assert [fragment.role for fragment in answer.fragments] == [
        FragmentRole.SUBCLASS,
        FragmentRole.IMPORTER,
        FragmentRole.CALLER,
    ]


async def test_unknown_symbol_does_not_reach_the_graph() -> None:
    reader = FakeSymbolReader(by_name={})

    answer = await build_navigator(reader).find_references("NoSuchClass")

    assert answer.is_empty
    assert reader.asked_kinds == []
