import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { HunkData } from "react-diff-view";
import {
  Decoration,
  Diff,
  findChangeByNewLineNumber,
  findChangeByOldLineNumber,
  getChangeKey,
  Hunk,
  parseDiff,
} from "react-diff-view";

import { api } from "@/api/client";
import type { Finding, ReviewFile } from "@/api/types";
import { FindingCard } from "@/components/FindingCard";
import { SEVERITY_ORDER } from "@/components/SeverityMark";

interface Props {
  runId: string;
  file: ReviewFile;
  findings: Finding[];
}

const CHANGE_LABEL: Record<string, string> = {
  added: "добавлен",
  modified: "изменён",
  deleted: "удалён",
  renamed: "переименован",
};

export function FileDiff({ runId, file, findings }: Props) {
  const [isOpen, setIsOpen] = useState(findings.length > 0);

  /* Файл раскрывается сам, когда под текущий фильтр попали его замечания:
     иначе включённый фильтр показывал бы список свёрнутых файлов. */
  useEffect(() => {
    if (findings.length > 0) {
      setIsOpen(true);
    }
  }, [findings.length]);

  return (
    <section className="border border-tweed-dim bg-ink-raised">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-ink-hover"
      >
        <span aria-hidden className="font-mono text-[13px] text-paper-dim">
          {isOpen ? "▾" : "▸"}
        </span>
        <span className="truncate font-mono text-[14px] text-paper">{file.path}</span>
        <span className="case-label ml-auto shrink-0">
          {CHANGE_LABEL[file.change_type] ?? file.change_type}
          <span className="mx-2 text-diff-add">+{file.added_lines}</span>
          <span className="text-diff-del">−{file.removed_lines}</span>
          {findings.length > 0 ? (
            <span className="ml-3 text-brass">находок {findings.length}</span>
          ) : null}
        </span>
      </button>

      {isOpen ? <FileBody runId={runId} file={file} findings={findings} /> : null}
    </section>
  );
}

function FileBody({ runId, file, findings }: Props) {
  const patch = useQuery({
    queryKey: ["patch", runId, file.id],
    queryFn: () => api.getFilePatch(runId, file.id),
    enabled: !file.is_too_large,
    staleTime: Infinity,
  });

  const parsed = useMemo(() => {
    if (!patch.data?.patch) {
      return null;
    }
    return parseDiff(patch.data.patch, { nearbySequences: "zip" })[0] ?? null;
  }, [patch.data?.patch]);

  const placement = useMemo(
    () => placeFindings(runId, findings, parsed?.hunks ?? []),
    [runId, findings, parsed],
  );

  if (file.is_too_large) {
    return (
      <div className="border-t border-tweed-dim">
        <p className="px-5 py-4 text-[15px] text-paper-dim">
          Файл слишком велик для показа. Замечания по нему собраны ниже, сам дифф удобнее
          смотреть в редакторе.
        </p>
        <DetachedFindings runId={runId} findings={findings} title="Замечания по файлу" />
      </div>
    );
  }

  if (patch.isPending) {
    return <p className="case-label border-t border-tweed-dim px-5 py-4">читаю файл…</p>;
  }

  if (patch.isError || !parsed) {
    return (
      <p className="border-t border-tweed-dim px-5 py-4 text-[15px] text-critical">
        Не удалось получить дифф этого файла.
      </p>
    );
  }

  return (
    <div className="border-t border-tweed-dim">
      <div className="overflow-x-auto">
        <Diff
          viewType="unified"
          diffType={parsed.type}
          hunks={parsed.hunks}
          widgets={placement.widgets}
          className="diff"
        >
          {(hunks) =>
            hunks.flatMap((hunk) => [
              <Decoration key={`decoration-${hunk.content}`} className="diff-hunk-header">
                <span className="diff-hunk-header-content font-mono">{hunk.content}</span>
              </Decoration>,
              <Hunk key={hunk.content} hunk={hunk} />,
            ])
          }
        </Diff>
      </div>

      <DetachedFindings
        runId={runId}
        findings={placement.detached}
        title="Замечания вне показанных строк"
      />
    </div>
  );
}

interface DetachedProps {
  runId: string;
  findings: Finding[];
  title: string;
}

/**
 * Замечания, которые не удалось привязать к строке диффа, показываются отдельно.
 * Молча терять их нельзя: они уже прошли проверку доказательств.
 */
function DetachedFindings({ runId, findings, title }: DetachedProps) {
  if (findings.length === 0) {
    return null;
  }

  return (
    <div className="border-t border-tweed-dim bg-ink px-5 py-4">
      <p className="case-label mb-3">
        {title} · {findings.length}
      </p>
      <div className="space-y-3">
        {sortBySeverity(findings).map((finding) => (
          <FindingCard key={finding.id} runId={runId} finding={finding} />
        ))}
      </div>
    </div>
  );
}

interface Placement {
  widgets: Record<string, React.ReactNode>;
  detached: Finding[];
}

/**
 * Ключ виджета берётся у самой библиотеки: он различается для добавленных,
 * удалённых и контекстных строк, и угадывать его формат нельзя.
 */
function placeFindings(runId: string, findings: Finding[], hunks: HunkData[]): Placement {
  const byKey = new Map<string, Finding[]>();
  const detached: Finding[] = [];

  for (const finding of findings) {
    const change =
      finding.side === "old"
        ? findChangeByOldLineNumber(hunks, finding.line_start)
        : findChangeByNewLineNumber(hunks, finding.line_start);

    if (!change) {
      detached.push(finding);
      continue;
    }

    const key = getChangeKey(change);
    byKey.set(key, [...(byKey.get(key) ?? []), finding]);
  }

  const widgets: Record<string, React.ReactNode> = {};
  for (const [key, lineFindings] of byKey) {
    widgets[key] = (
      <div className="space-y-3 bg-ink px-5 py-5">
        {sortBySeverity(lineFindings).map((finding) => (
          <FindingCard key={finding.id} runId={runId} finding={finding} />
        ))}
      </div>
    );
  }

  return { widgets, detached };
}

function sortBySeverity(findings: Finding[]): Finding[] {
  return [...findings].sort(
    (first, second) =>
      SEVERITY_ORDER.indexOf(first.severity) - SEVERITY_ORDER.indexOf(second.severity),
  );
}
