import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { HunkData } from "react-diff-view";
import {
  Decoration,
  Diff,
  findChangeByNewLineNumber,
  findChangeByOldLineNumber,
  getChangeKey,
  getCollapsedLinesCountBetween,
  Hunk,
  insertHunk,
  parseDiff,
  textLinesToHunk,
} from "react-diff-view";

import { api } from "@/api/client";
import type { DiffSide, Finding, ReviewFile } from "@/api/types";
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

/** Тип изменения различается цветом штампа, а не только словом. */
const CHANGE_TAG: Record<string, string> = {
  added: "tag-added",
  modified: "tag-modified",
  deleted: "tag-deleted",
  renamed: "tag-renamed",
};

const EXPAND_STEP = 20;

/** Совпадает с MAX_CONTEXT_WINDOW_LINES на сервере: больше он всё равно не отдаст. */
const MAX_EXPAND_LINES = 400;

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
        className="file-tab flex w-full items-center gap-3 px-5 py-3 text-left"
      >
        <span aria-hidden className="font-mono text-[13px] opacity-60">
          {isOpen ? "▾" : "▸"}
        </span>
        <span className="truncate font-mono text-[14px] font-bold">{file.path}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <span className={`tag tag-stamp ${CHANGE_TAG[file.change_type] ?? "tag-modified"}`}>
            {CHANGE_LABEL[file.change_type] ?? file.change_type}
          </span>
          <span className="tag tag-add">+{file.added_lines}</span>
          <span className="tag tag-del">−{file.removed_lines}</span>
          {findings.length > 0 ? (
            <span className="tag tag-findings">находок {findings.length}</span>
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

  const patchData = patch.data;
  const parsed = useMemo(() => {
    if (!patchData?.patch) {
      return null;
    }
    return parseDiff(patchData.patch, { nearbySequences: "zip" })[0] ?? null;
  }, [patchData?.patch]);

  const { applyTo, expand, isBusy, hasFailed } = useContextExpansion(
    runId,
    file.id,
    patchData?.context_side,
  );
  const hunks = useMemo(() => applyTo(parsed?.hunks ?? []), [applyTo, parsed]);

  const placement = useMemo(
    () => placeFindings(runId, findings, hunks),
    [runId, findings, hunks],
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

  if (patch.isError || !patchData || !parsed) {
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
          hunks={hunks}
          widgets={placement.widgets}
          className="diff"
        >
          {(rendered) => {
            const tail = trailingGap(rendered, patchData.context_side, patchData.total_lines);

            return [
              ...rendered.flatMap((hunk, index) => [
                <Decoration key={`decoration-${hunk.content}`} className="diff-hunk-header">
                  <span className="diff-hunk-header-content flex flex-wrap items-center gap-3 font-mono">
                    <ExpandControls
                      gap={collapsedGap(rendered[index - 1] ?? null, hunk)}
                      isBusy={isBusy}
                      onExpand={expand}
                    />
                    <span>{hunk.content}</span>
                  </span>
                </Decoration>,
                <Hunk key={hunk.content} hunk={hunk} />,
              ]),
              ...(tail
                ? [
                    <Decoration key="tail" className="diff-hunk-header">
                      <span className="diff-hunk-header-content flex flex-wrap items-center gap-3 font-mono">
                        <ExpandControls gap={tail} isBusy={isBusy} onExpand={expand} />
                        <span>до конца файла</span>
                      </span>
                    </Decoration>,
                  ]
                : []),
            ];
          }}
        </Diff>
      </div>

      {hasFailed ? (
        <p className="border-t border-tweed-dim px-5 py-3 text-[14px] text-critical">
          Не удалось прочитать файл в этой ревизии — контекст не раскрыт.
        </p>
      ) : null}

      <DetachedFindings
        runId={runId}
        findings={placement.detached}
        title="Замечания вне показанных строк"
      />
    </div>
  );
}

interface Gap {
  oldStart: number;
  newStart: number;
  lines: number;
}

/**
 * Свёрнутый участок перед ханком. Границы считаются по старым номерам строк —
 * так их считает и сама библиотека, — а новые нужны для сборки вставляемого блока.
 */
function collapsedGap(previous: HunkData | null, next: HunkData): Gap | null {
  const lines = getCollapsedLinesCountBetween(previous, next);
  if (lines <= 0) {
    return null;
  }

  return {
    oldStart: previous ? previous.oldStart + previous.oldLines : 1,
    newStart: previous ? previous.newStart + previous.newLines : 1,
    lines,
  };
}

/**
 * Остаток файла после последнего изменения. Из самого диффа его длину узнать
 * нельзя, поэтому она приходит вместе с патчем: без неё изменение в конце файла
 * неотличимо от того, за которым идёт ещё код.
 */
function trailingGap(hunks: HunkData[], side: DiffSide, totalLines: number | null): Gap | null {
  const last = hunks[hunks.length - 1];
  if (!last || totalLines === null) {
    return null;
  }

  const oldStart = last.oldStart + last.oldLines;
  const newStart = last.newStart + last.newLines;
  const start = side === "old" ? oldStart : newStart;
  const lines = totalLines - start + 1;

  return lines > 0 ? { oldStart, newStart, lines } : null;
}

interface ExpandControlsProps {
  gap: Gap | null;
  isBusy: boolean;
  onExpand: (gap: Gap, lines: number, fromEnd: boolean) => void;
}

/**
 * Большой пропуск раскрывается шагами с обоих концов: строка, соседняя
 * с изменением, обычно нужнее той, что лежит в середине пропуска.
 */
function ExpandControls({ gap, isBusy, onExpand }: ExpandControlsProps) {
  if (!gap) {
    return null;
  }

  if (gap.lines <= EXPAND_STEP) {
    return (
      <ExpandButton
        label={`показать ${gap.lines}`}
        isBusy={isBusy}
        onClick={() => onExpand(gap, gap.lines, false)}
      />
    );
  }

  return (
    <span className="flex flex-wrap items-center gap-2">
      <ExpandButton
        label={`${EXPAND_STEP} сверху`}
        isBusy={isBusy}
        onClick={() => onExpand(gap, EXPAND_STEP, false)}
      />
      <ExpandButton
        label={`${EXPAND_STEP} снизу`}
        isBusy={isBusy}
        onClick={() => onExpand(gap, EXPAND_STEP, true)}
      />
      {gap.lines <= MAX_EXPAND_LINES ? (
        <ExpandButton
          label={`все ${gap.lines}`}
          isBusy={isBusy}
          onClick={() => onExpand(gap, gap.lines, false)}
        />
      ) : null}
    </span>
  );
}

interface ExpandButtonProps {
  label: string;
  isBusy: boolean;
  onClick: () => void;
}

function ExpandButton({ label, isBusy, onClick }: ExpandButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isBusy}
      className="rounded-case border border-tweed-dim px-2.5 py-0.5 text-[12px] tracking-wide text-paper-dim transition-colors hover:border-brass hover:text-brass disabled:opacity-40"
    >
      {label}
    </button>
  );
}

interface Expansion {
  applyTo: (hunks: HunkData[]) => HunkData[];
  expand: (gap: Gap, lines: number, fromEnd: boolean) => void;
  isBusy: boolean;
  hasFailed: boolean;
}

/**
 * Раскрытие контекста вокруг изменений. Строки не приходят вместе с патчем:
 * они читаются из ревизии по требованию и вставляются в дифф отдельными блоками,
 * чтобы неоткрытые куски файла не грузились никогда.
 *
 * Сторону выбирает сервер и присылает вместе с патчем: длина файла посчитана
 * именно для неё, и разъехаться эти два решения не должны.
 */
function useContextExpansion(runId: string, fileId: string, side: DiffSide | undefined): Expansion {
  const queryClient = useQueryClient();
  const [insertions, setInsertions] = useState<HunkData[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [hasFailed, setHasFailed] = useState(false);

  const expand = useCallback(
    (gap: Gap, lines: number, fromEnd: boolean) => {
      if (!side) {
        return;
      }

      const offset = fromEnd ? gap.lines - lines : 0;
      const oldStart = gap.oldStart + offset;
      const newStart = gap.newStart + offset;
      const startLine = side === "old" ? oldStart : newStart;

      setIsBusy(true);
      setHasFailed(false);

      queryClient
        .fetchQuery({
          queryKey: ["context", runId, fileId, side, startLine, lines],
          queryFn: () =>
            api.getFileContext(runId, fileId, {
              side,
              startLine,
              endLine: startLine + lines - 1,
            }),
          staleTime: Infinity,
        })
        .then((context) => {
          const hunk = textLinesToHunk(context.lines, oldStart, newStart);
          if (hunk) {
            setInsertions((all) => [...all, hunk]);
          }
        })
        .catch(() => setHasFailed(true))
        .finally(() => setIsBusy(false));
    },
    [queryClient, runId, fileId, side],
  );

  const applyTo = useCallback(
    (hunks: HunkData[]) =>
      insertions.reduce((all, insertion) => insertHunk(all, insertion), hunks),
    [insertions],
  );

  return { applyTo, expand, isBusy, hasFailed };
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
