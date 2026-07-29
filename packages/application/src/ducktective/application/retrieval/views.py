from dataclasses import (
    dataclass,
)

from ducktective.core.indexing.value_objects import (
    SymbolKind,
)
from ducktective.core.types import (
    QualifiedName,
)


@dataclass(frozen=True, kw_only=True)
class CodeMatchView:
    """Фрагмент кода, найденный поиском.

    Координаты обязательны: клиент, получивший фрагмент, должен уметь открыть
    его в файле, а не только прочитать текст.
    """

    path: str
    breadcrumb: str
    start_line: int
    end_line: int
    content: str
    score: float

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, kw_only=True)
class SymbolView:
    """Символ вместе с текстом и местом в файле."""

    qualified_name: QualifiedName
    kind: SymbolKind
    path: str
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None
    text: str

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, kw_only=True)
class SymbolNeighbourhoodView:
    """Символы участка файла вместе с их соседями по графу.

    Соседи приходят без тела: от них нужен контракт, и телом один крупный
    класс вытеснил бы всё остальное.
    """

    path: str
    start_line: int
    end_line: int
    symbols: tuple[SymbolView, ...] = ()
    callees: tuple[SymbolView, ...] = ()
    callers: tuple[SymbolView, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.symbols
