import { useState } from "react";

interface Props {
  name: string;
  arguments: string;
  result: string;
  dense?: boolean;
}

const TOOL_LABEL: Record<string, string> = {
  search_code: "ищет по смыслу",
  get_definition: "читает определение",
  find_callers: "смотрит, кто вызывает",
  get_file_context: "смотрит окружение",
  find_symbol: "ищет символ",
  read_file: "читает файл",
  list_files: "смотрит, что есть",
  get_file_outline: "смотрит состав файла",
  describe_repository: "осматривается",
  project_docs: "читает документацию",
  search_document: "ищет в документе",
};

/**
 * Что агент спросил у кодовой базы и что получил.
 *
 * Показывается свёрнутым: ответ важнее источников, но проверить источник
 * должно быть можно — иначе утверждение о чужом коде нечем подтвердить.
 */
export function ToolCard({ name, arguments: args, result, dense = false }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const label = TOOL_LABEL[name] ?? name;

  return (
    <div className={dense ? "tool-card px-2.5 py-1" : "tool-card px-3 py-2"}>
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        className="flex w-full items-baseline gap-2 text-left"
      >
        <span className={`case-label text-brass ${dense ? "shrink-0" : ""}`}>{label}</span>
        <span
          className={`truncate font-mono text-paper-dim ${dense ? "text-[11px]" : "text-[12px]"}`}
        >
          {summarize(args)}
        </span>
        <span
          className={`ml-auto shrink-0 font-mono text-paper-dim ${
            dense ? "text-[11px]" : "text-[12px]"
          }`}
        >
          {result ? (isOpen ? "свернуть −" : "показать +") : "ищу…"}
        </span>
      </button>

      {isOpen && result ? (
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-paper-dim">
          {result}
        </pre>
      ) : null}
    </div>
  );
}

function summarize(args: string): string {
  if (!args) {
    return "";
  }
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>;
    return Object.values(parsed).map(String).join(" · ");
  } catch {
    return args.slice(0, 80);
  }
}
