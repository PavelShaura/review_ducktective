import { useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  name: string;
  arguments: string;
  result: string;
  dense?: boolean;
}

const KNOWN_TOOLS = [
  "search_code",
  "get_definition",
  "find_callers",
  "get_file_context",
  "find_symbol",
  "read_file",
  "list_files",
  "get_file_outline",
  "describe_repository",
  "project_docs",
  "search_document",
] as const;

type KnownTool = (typeof KNOWN_TOOLS)[number];

function isKnownTool(name: string): name is KnownTool {
  return (KNOWN_TOOLS as readonly string[]).includes(name);
}

/**
 * Что агент спросил у кодовой базы и что получил.
 *
 * Показывается свёрнутым: ответ важнее источников, но проверить источник
 * должно быть можно — иначе утверждение о чужом коде нечем подтвердить.
 */
export function ToolCard({ name, arguments: args, result, dense = false }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useTranslation();
  const label = isKnownTool(name) ? t(`tool.${name}`) : name;

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
          {result
            ? isOpen
              ? t("common.collapseLess")
              : t("common.expandMore")
            : t("tool.searching")}
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
