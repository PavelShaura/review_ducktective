import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "@/api/client";
import type { FeedbackVerdict, Finding, ReviewRun, Severity } from "@/api/types";
import { FileDiff } from "@/components/FileDiff";
import { FindingCard } from "@/components/FindingCard";
import { ContextMark } from "@/components/ContextMark";
import { SEVERITY_LABEL, SEVERITY_ORDER, SEVERITY_TEXT } from "@/components/SeverityMark";
import {
  ReviewCancelled,
  ReviewDegraded,
  ReviewFailure,
  ReviewProgress,
} from "@/components/ReviewProgress";
import { isInProgress, StatusMark } from "@/components/StatusMark";
import { VERDICT_LABEL, VERDICT_ORDER, VERDICT_TEXT } from "@/components/VerdictStamp";
import { formatDateTime, shortSha } from "@/lib/format";

export default function CasePage() {
  const { runId = "" } = useParams();
  const [severityFilter, setSeverityFilter] = useState<Severity | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<FeedbackVerdict | null>(null);

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    refetchInterval: (query) =>
      query.state.data && isInProgress(query.state.data.status) ? 3000 : false,
  });

  const findingsByPath = useMemo(() => groupByPath(run.data?.findings ?? []), [run.data]);

  if (run.isPending) {
    return <p className="case-label py-16 text-center">поднимаю материалы дела…</p>;
  }

  if (run.isError) {
    return (
      <div className="py-20 text-center">
        <h2 className="font-display text-3xl text-paper">Дело не открывается</h2>
        <p className="mt-3 text-paper-dim">
          Проверьте, что сервис запущен и идентификатор дела верен.
        </p>
        <Link to="/" className="case-label mt-5 inline-block hover:text-brass">
          к списку дел
        </Link>
      </div>
    );
  }

  const hasFilter = severityFilter !== null || verdictFilter !== null;
  const visibleFiles = run.data.files.filter((file) => {
    if (!hasFilter) {
      return true;
    }
    const matched = selectFindings(
      findingsByPath.get(file.path) ?? [],
      severityFilter,
      verdictFilter,
    );
    return matched.length > 0;
  });

  const isRunning = isInProgress(run.data.status);
  const hasFailed = run.data.status === "failed";
  const wasCancelled = run.data.status === "cancelled";

  return (
    <div className="space-y-8">
      <CaseHeader run={run.data} />

      {isRunning ? <ReviewProgress run={run.data} /> : null}
      {hasFailed ? <ReviewFailure run={run.data} /> : null}
      {wasCancelled ? <ReviewCancelled run={run.data} /> : null}

      {isRunning || hasFailed || wasCancelled ? null : <ReviewDegraded run={run.data} />}

      {isRunning || hasFailed || wasCancelled ? null : (
        <SeverityFilter
          findings={run.data.findings}
          active={severityFilter}
          onChange={setSeverityFilter}
          verdictFilter={verdictFilter}
          onVerdictChange={setVerdictFilter}
        />
      )}

      <div className="space-y-3">
        {visibleFiles.map((file) => (
          <FileDiff
            key={file.id}
            runId={run.data.id}
            file={file}
            findings={selectFindings(
              findingsByPath.get(file.path) ?? [],
              severityFilter,
              verdictFilter,
            )}
          />
        ))}
        {visibleFiles.length === 0 ? (
          <p className="py-10 text-center text-paper-dim">
            Под этот фильтр не попал ни один файл.
          </p>
        ) : null}
      </div>

      <UnmatchedFindings
        runId={run.data.id}
        findings={findWithoutFiles(run.data, severityFilter, verdictFilter)}
      />
    </div>
  );
}

interface UnmatchedProps {
  runId: string;
  findings: Finding[];
}

/** Замечания, чей файл отсутствует в диффе: показываем, а не теряем. */
function UnmatchedFindings({ runId, findings }: UnmatchedProps) {
  if (findings.length === 0) {
    return null;
  }

  return (
    <section className="border border-tweed-dim bg-ink-raised">
      <p className="case-label border-b border-tweed-dim px-5 py-3">
        замечания без файла в диффе · {findings.length}
      </p>
      <div className="space-y-3 px-5 py-4">
        {findings.map((finding) => (
          <FindingCard key={finding.id} runId={runId} finding={finding} />
        ))}
      </div>
    </section>
  );
}

function findWithoutFiles(
  run: ReviewRun,
  severity: Severity | null,
  verdict: FeedbackVerdict | null,
): Finding[] {
  const knownPaths = new Set(run.files.map((file) => file.path));
  const orphans = run.findings.filter((finding) => !knownPaths.has(finding.file_path));
  return selectFindings(orphans, severity, verdict);
}

function CaseHeader({ run }: { run: ReviewRun }) {
  return (
    <header className="border border-tweed-dim bg-ink-raised px-5 py-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="case-label">дело</span>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-brass">
          {shortSha(run.id)}
        </h1>
        <StatusMark status={run.status} />
        <span className="ml-auto">
          <ContextMark run={run} />
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-8 gap-y-1.5 sm:grid-cols-4">
        <Fact label="ревизии" value={`${shortSha(run.base_sha)} → ${shortSha(run.head_sha)}`} />
        <Fact label="файлов" value={String(run.files.length)} />
        <Fact label="находок" value={String(run.findings.length)} />
        <Fact label="заведено" value={formatDateTime(run.created_at)} />
      </dl>
    </header>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="case-label">{label}</dt>
      <dd className="truncate font-mono text-[14px] text-paper">{value}</dd>
    </div>
  );
}

interface FilterProps {
  findings: Finding[];
  active: Severity | null;
  onChange: (severity: Severity | null) => void;
  verdictFilter: FeedbackVerdict | null;
  onVerdictChange: (verdict: FeedbackVerdict | null) => void;
}

/**
 * Счёт ведётся по самим находкам, а не по сводке прогона: сводка исключает
 * отклонённые, и после разметки уровень пропадал бы из фильтра, оставаясь
 * при этом на странице.
 */
function SeverityFilter({
  findings,
  active,
  onChange,
  verdictFilter,
  onVerdictChange,
}: FilterProps) {
  const counts = countBySeverity(findings);
  const present = SEVERITY_ORDER.filter((severity) => counts[severity] > 0);
  const verdictCounts = countByVerdict(findings);
  const markedVerdicts = VERDICT_ORDER.filter((verdict) => verdictCounts[verdict] > 0);

  if (present.length === 0) {
    return (
      <p className="border border-confirmed/30 bg-confirmed/5 px-5 py-5 text-[16px] text-paper">
        Замечаний нет — в изменённых строках проблем не найдено.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <FilterButton
        label={`все ${findings.length}`}
        active={active === null}
        onClick={() => onChange(null)}
      />
      {present.map((severity) => (
        <FilterButton
          key={severity}
          label={`${SEVERITY_LABEL[severity]} ${counts[severity]}`}
          active={active === severity}
          className={SEVERITY_TEXT[severity]}
          onClick={() => onChange(active === severity ? null : severity)}
        />
      ))}
      {markedVerdicts.length > 0 ? (
        <span aria-hidden className="mx-1 h-5 w-px bg-tweed-dim" />
      ) : null}

      {markedVerdicts.map((verdict) => (
        <FilterButton
          key={verdict}
          label={`${VERDICT_LABEL[verdict]} ${verdictCounts[verdict]}`}
          active={verdictFilter === verdict}
          className={VERDICT_TEXT[verdict]}
          onClick={() => onVerdictChange(verdictFilter === verdict ? null : verdict)}
        />
      ))}
    </div>
  );
}

function countByVerdict(findings: Finding[]): Record<FeedbackVerdict, number> {
  const counts: Record<FeedbackVerdict, number> = {
    useful: 0,
    false_positive: 0,
    wontfix: 0,
  };
  for (const finding of findings) {
    if (finding.latest_verdict) {
      counts[finding.latest_verdict] += 1;
    }
  }
  return counts;
}

function countBySeverity(findings: Finding[]): Record<Severity, number> {
  const counts: Record<Severity, number> = {
    critical: 0,
    major: 0,
    minor: 0,
    nitpick: 0,
  };
  for (const finding of findings) {
    counts[finding.severity] += 1;
  }
  return counts;
}

interface FilterButtonProps {
  label: string;
  active: boolean;
  className?: string;
  onClick: () => void;
}

function FilterButton({ label, active, className = "", onClick }: FilterButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-case border px-3.5 py-1.5 font-mono text-[12px] tracking-wide transition-colors ${
        active
          ? `border-brass bg-brass/10 ${className || "text-brass"}`
          : `border-tweed-dim hover:border-tweed ${className || "text-paper-dim"}`
      }`}
    >
      {label}
    </button>
  );
}

function groupByPath(findings: Finding[]): Map<string, Finding[]> {
  const grouped = new Map<string, Finding[]>();
  for (const finding of findings) {
    grouped.set(finding.file_path, [...(grouped.get(finding.file_path) ?? []), finding]);
  }
  return grouped;
}

function filterFindings(findings: Finding[], severity: Severity | null): Finding[] {
  return severity ? findings.filter((finding) => finding.severity === severity) : findings;
}

/** Фильтры складываются: можно смотреть, например, только отклонённые мелочи. */
function selectFindings(
  findings: Finding[],
  severity: Severity | null,
  verdict: FeedbackVerdict | null,
): Finding[] {
  const bySeverity = filterFindings(findings, severity);
  return verdict
    ? bySeverity.filter((finding) => finding.latest_verdict === verdict)
    : bySeverity;
}
