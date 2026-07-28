from dataclasses import (
    dataclass,
    field,
)
from enum import (
    StrEnum,
)

from ducktective.core.types import (
    CodeSymbolId,
    QualifiedName,
)


class ContextOrigin(StrEnum):
    """Откуда взялся фрагмент контекста.

    Порядок членов задаёт приоритет при упаковке под бюджет: структурные
    соседи точны по построению, результаты поиска вероятностны, поэтому
    первые вытесняют вторых, а не наоборот.
    """

    CHANGED_SYMBOL = "changed_symbol"
    CALLEE = "callee"
    CALLER = "caller"
    SIMILAR = "similar"


ORIGIN_PRIORITY = {
    ContextOrigin.CHANGED_SYMBOL: 0,
    ContextOrigin.CALLEE: 1,
    ContextOrigin.CALLER: 2,
    ContextOrigin.SIMILAR: 3,
}


@dataclass(frozen=True, kw_only=True)
class ContextPiece:
    """Фрагмент кода, попадающий в подсказку модели.

    Каждый такой фрагмент — кандидат в доказательство находки: модель может
    ссылаться только на то, что действительно видела.
    """

    origin: ContextOrigin
    path: str
    qualified_name: QualifiedName | None
    start_line: int
    end_line: int
    text: str
    token_count: int
    symbol_id: CodeSymbolId | None = None

    @property
    def location(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"


@dataclass(frozen=True, kw_only=True)
class DiffContext:
    """Контекст, собранный вокруг изменений одного файла."""

    path: str
    pieces: tuple[ContextPiece, ...] = ()
    dropped: int = 0
    token_budget: int = 0

    @property
    def token_count(self) -> int:
        return sum(piece.token_count for piece in self.pieces)

    @property
    def is_empty(self) -> bool:
        return not self.pieces

    def of_origin(self, origin: ContextOrigin) -> tuple[ContextPiece, ...]:
        return tuple(piece for piece in self.pieces if piece.origin is origin)


@dataclass
class ContextBudget:
    """Учёт места, оставшегося под контекст.

    Бюджет считается в токенах, а не в фрагментах: десять коротких сигнатур
    полезнее одного длинного класса, и решать это должен размер, а не счёт.
    """

    limit: int
    used: int = 0
    dropped: int = 0
    seen: set[str] = field(default_factory=set)

    def take(self, piece: ContextPiece) -> bool:
        key = f"{piece.path}:{piece.start_line}:{piece.end_line}"
        if key in self.seen:
            return False

        if self.used + piece.token_count > self.limit:
            self.dropped += 1
            return False

        self.seen.add(key)
        self.used += piece.token_count
        return True
