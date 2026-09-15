import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { FeedbackDigest, FeedbackVerdict, MarkedFinding, Repository } from "@/api/types";
import { SEVERITY_TEXT } from "@/components/SeverityMark";
import { VERDICT_ORDER, VERDICT_TEXT } from "@/components/VerdictStamp";
import { formatDateTime, shortSha } from "@/lib/format";

export default function MarksPage() {
  const { t } = useTranslation();
  const repositories = useQuery({
    queryKey: ["repositories"],
    queryFn: api.listRepositories,
  });

  if (repositories.isPending) {
    return <p className="case-label py-16 text-center">{t("marks.loading")}</p>;
  }

  if (repositories.isError) {
    return <p className="py-20 text-center text-paper-dim">{t("marks.unavailable")}</p>;
  }

  if (repositories.data.length === 0) {
    return <p className="py-20 text-center text-paper-dim">{t("marks.nothing")}</p>;
  }

  return (
    <div className="space-y-14">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">{t("marks.title")}</h1>
        <p className="mt-2 max-w-2xl text-[15px] text-paper-dim">{t("marks.intro")}</p>
      </header>

      {repositories.data.map((repository) => (
        <RepositoryMarks key={repository.id} repository={repository} />
      ))}
    </div>
  );
}

function RepositoryMarks({ repository }: { repository: Repository }) {
  const { t } = useTranslation();
  const [verdictFilter, setVerdictFilter] = useState<FeedbackVerdict | null>(null);

  const digest = useQuery({
    queryKey: ["feedback", repository.id],
    queryFn: () => api.getFeedbackDigest(repository.id),
  });

  if (!digest.data) {
    return null;
  }

  const visible = verdictFilter
    ? digest.data.marked.filter((item) => item.verdict === verdictFilter)
    : digest.data.marked;

  return (
    <section>
      <h2 className="mb-4 font-display text-2xl font-semibold text-paper">{repository.name}</h2>

      <Summary digest={digest.data} active={verdictFilter} onChange={setVerdictFilter} />

      {digest.data.marked.length === 0 ? (
        <p className="mt-4 border border-tweed-dim bg-ink-raised px-5 py-6 text-[15px] text-paper-dim">
          {t("marks.noneMarked")}
        </p>
      ) : (
        <ol className="mt-4 space-y-2">
          {visible.map((item) => (
            <MarkRow key={item.finding_id} mark={item} />
          ))}
        </ol>
      )}
    </section>
  );
}

interface SummaryProps {
  digest: FeedbackDigest;
  active: FeedbackVerdict | null;
  onChange: (verdict: FeedbackVerdict | null) => void;
}

function Summary({ digest, active, onChange }: SummaryProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border border-tweed-dim bg-ink-raised px-5 py-4">
      <span className="case-label">
        {t("marks.marked")} <span className="tabular-nums text-paper">{digest.marked_count}</span>{" "}
        {t("marks.of")} <span className="tabular-nums">{digest.total_findings}</span>
      </span>

      <span aria-hidden className="mx-1 h-5 w-px bg-tweed-dim" />

      {VERDICT_ORDER.map((verdict) => (
        <VerdictFilter
          key={verdict}
          verdict={verdict}
          count={digest.counts[verdict] ?? 0}
          active={active === verdict}
          onClick={() => onChange(active === verdict ? null : verdict)}
        />
      ))}

      {digest.useful_share === null ? null : (
        <span className="case-label ml-auto">
          {t("marks.usefulShare")}{" "}
          <span className="tabular-nums text-brass">
            {(digest.useful_share * 100).toFixed(0)}%
          </span>
        </span>
      )}
    </div>
  );
}

interface VerdictFilterProps {
  verdict: FeedbackVerdict;
  count: number;
  active: boolean;
  onClick: () => void;
}

function VerdictFilter({ verdict, count, active, onClick }: VerdictFilterProps) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      disabled={count === 0}
      className={`rounded-case border px-3.5 py-1.5 font-mono text-[12px] tracking-wide transition-colors disabled:opacity-40 ${
        active
          ? `border-brass bg-brass/10 ${VERDICT_TEXT[verdict]}`
          : `border-tweed-dim hover:border-tweed ${VERDICT_TEXT[verdict]}`
      }`}
    >
      {t(`verdict.${verdict}`)} <span className="tabular-nums">{count}</span>
    </button>
  );
}

function MarkRow({ mark }: { mark: MarkedFinding }) {
  const { t } = useTranslation();
  return (
    <li className="rounded-case border border-tweed-dim bg-ink-raised transition-colors hover:border-brass">
      <Link to={`/cases/${mark.run_id}`} className="block px-5 py-3.5">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`case-label ${VERDICT_TEXT[mark.verdict]}`}>
            {t(`verdict.${mark.verdict}`)}
          </span>
          <span className={`case-label ${SEVERITY_TEXT[mark.severity]}`}>
            {t(`severity.${mark.severity}`)}
          </span>
          <span className="min-w-0 flex-1 truncate text-[15px] text-paper">{mark.title}</span>
          <span className="case-label shrink-0">{formatDateTime(mark.marked_at)}</span>
        </div>

        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 font-mono text-[13px] text-paper-dim">
          <span className="truncate">
            {mark.file_path}:{mark.line_start}
          </span>
          <span className="opacity-40">·</span>
          <span>{t("marks.caseLabel", { sha: shortSha(mark.run_id) })}</span>
        </div>

        {mark.comment ? (
          <p className="mt-2 text-[14px] text-paper-dim">{mark.comment}</p>
        ) : null}
      </Link>
    </li>
  );
}
