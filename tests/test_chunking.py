from ducktective.core.indexing.entities import (
    CodeChunk,
)
from ducktective.indexing.chunking import (
    MAX_CHUNK_TOKENS,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)


def chunks_of(content: str, path: str = "app/report.py") -> list[CodeChunk]:
    return PythonParser().parse(path=path, content=content).chunks


def build_long_method(name: str, lines: int) -> str:
    body = "\n".join(f"        value_{number} = compute({number})" for number in range(lines))
    return f"    def {name}(self):\n{body}\n        return value_0\n"


def test_module_level_code_becomes_its_own_chunk() -> None:
    chunks = chunks_of(
        "import json\nfrom decimal import Decimal\n\nRATE = Decimal('0.2')\n\n"
        "def render(report):\n    return json.dumps(report)\n"
    )

    module_chunk = chunks[0]
    assert "import json" in module_chunk.content
    assert "RATE" in module_chunk.content
    assert "def render" not in module_chunk.content


def test_small_definition_keeps_its_symbol() -> None:
    chunks = chunks_of(
        "class Builder:\n"
        "    def build(self):\n"
        "        return self.collect() + self.render() + self.finish()\n"
    )

    chunk = next(chunk for chunk in chunks if "def build" in chunk.content)
    assert chunk.symbol_id is not None
    assert chunk.breadcrumb == "app.report > Builder"


def test_large_class_is_split_by_its_methods() -> None:
    source = "class Wide:\n" + "\n".join(
        build_long_method(f"method_{number}", 40) for number in range(4)
    )

    chunks = chunks_of(source)

    assert len(chunks) > 1
    assert all(chunk.token_count <= MAX_CHUNK_TOKENS for chunk in chunks)


def test_oversized_body_without_inner_definitions_is_cut_by_lines() -> None:
    source = "class Huge:\n" + build_long_method("giant", 600)

    chunks = chunks_of(source)

    assert len(chunks) > 1
    assert all(chunk.token_count <= MAX_CHUNK_TOKENS * 2 for chunk in chunks)


def test_merged_neighbours_report_their_common_owner() -> None:
    """Склеенный чанк не притворяется одним из склеенных методов."""
    source = (
        "class Builder:\n"
        "    def first(self):\n        return 1\n\n"
        "    def second(self):\n        return 2\n\n"
        "    def third(self):\n        return 3\n"
    )

    chunks = chunks_of(source)

    merged = [chunk for chunk in chunks if chunk.content.count("def ") > 1]
    assert merged
    assert all(chunk.breadcrumb == "app.report > Builder" for chunk in merged)


def test_chunk_lines_point_back_into_the_file() -> None:
    source = "import json\n\n\nclass Builder:\n    def build(self):\n        return json\n"

    chunks = chunks_of(source)
    lines = source.splitlines()

    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)
        assert chunk.content.strip().splitlines()[0].strip() in lines[chunk.start_line - 1]


def test_breadcrumb_names_the_module_in_import_form() -> None:
    chunks = chunks_of("import json\n", path="packages/core/src/app/report.py")

    assert chunks[0].breadcrumb == "app.report"


def test_identical_fragments_share_a_hash() -> None:
    first = chunks_of("def render(report):\n    return report\n", path="a/one.py")
    second = chunks_of("def render(report):\n    return report\n", path="b/two.py")

    assert first[0].content_hash == second[0].content_hash
