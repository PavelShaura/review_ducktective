from pathlib import (
    PurePosixPath,
)


LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".sql": "sql",
    ".sh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "scss",
    ".md": "markdown",
    ".txt": "text",
    ".cfg": "toml",
    ".ini": "toml",
    ".env": "text",
}

LANGUAGE_BY_FILENAME = {
    "Dockerfile": "dockerfile",
    "Makefile": "make",
}


def detect_language(path: str) -> str | None:
    """Определяет язык по имени файла. Неизвестные расширения не ошибка."""
    pure_path = PurePosixPath(path)
    by_name = LANGUAGE_BY_FILENAME.get(pure_path.name)
    if by_name is not None:
        return by_name
    return LANGUAGE_BY_EXTENSION.get(pure_path.suffix.lower())
