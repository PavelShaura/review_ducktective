import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { api } from "@/api/client";
import { DeleteCaseButton } from "@/components/DeleteCaseButton";
import { DeleteRepositoryButton } from "@/components/DeleteRepositoryButton";
import type { Repository, ReviewRunSummary, Severity } from "@/api/types";
import { SEVERITY_ORDER, SEVERITY_TEXT, SEVERITY_LABEL } from "@/components/SeverityMark";
import { StatusMark } from "@/components/StatusMark";
import { shortSha } from "@/lib/format";

export default function CaseListPage() {
  const repositories = useQuery({
    queryKey: ["repositories"],
    queryFn: api.listRepositories,
  });

  if (repositories.isPending) {
    return <p className="case-label py-16 text-center">просматриваю архив…</p>;
  }

  if (repositories.isError) {
    return (
      <Notice
        title="Архив недоступен"
        body="Сервис не отвечает. Запустите API командой ducktective serve и обновите страницу."
      />
    );
  }

  if (repositories.data.length === 0) {
    return (
      <Notice
        title="В архиве пусто"
        body="Ни одного репозитория пока не заведено. Заведите дело — укажите путь к репозиторию и ревизии."
        action={{ to: "/cases/new", label: "завести дело" }}
      />
    );
  }

  return (
    <div className="space-y-14">
      {repositories.data.map((repository) => (
        <RepositorySection key={repository.id} repository={repository} />
      ))}
    </div>
  );
}

function RepositorySection({ repository }: { repository: Repository }) {
  const runs = useQuery({
    queryKey: ["runs", repository.id],
    queryFn: () => api.listRuns(repository.id),
  });

  return (
    <section>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="font-display text-3xl font-semibold text-paper">{repository.name}</h2>
        <span className="case-label truncate">
          {repository.local_path}
          <span className="mx-2 opacity-40">·</span>
          {repository.egress_policy === "local_only" ? "только локально" : "облако разрешено"}
        </span>

        <DeleteRepositoryButton repositoryId={repository.id} name={repository.name} />
      </div>

      {runs.isError ? (
        <p className="border border-critical/50 bg-ink-raised px-5 py-6 text-[15px] text-critical">
          Дела этого репозитория не читаются: сервис ответил ошибкой. Загляните в журнал
          API — заведённые дела никуда не делись.
        </p>
      ) : runs.data && runs.data.length > 0 ? (
        <ol className="space-y-3">
          {runs.data.map((run) => (
            <CaseRow key={run.id} run={run} />
          ))}
        </ol>
      ) : (
        <p className="border border-tweed-dim bg-ink-raised px-5 py-6 text-[15px] text-paper-dim">
          По этому репозиторию дел ещё нет.
        </p>
      )}
    </section>
  );
}

function CaseRow({ run }: { run: ReviewRunSummary }) {
  const counts = run.severity_counts;

  return (
    <li className="flex items-center gap-3 rounded-case border border-tweed-dim bg-ink-raised pr-4 transition-colors hover:border-brass hover:bg-ink-hover">
      <Link to={`/cases/${run.id}`} className="min-w-0 flex-1 px-5 py-4">
        <span className="flex min-w-0 items-baseline gap-x-4">
          <span className="shrink-0 font-mono text-[14px] text-brass">{shortSha(run.id)}</span>
          {run.head_subject ? (
            <span className="truncate font-display text-[17px] font-semibold text-paper">
              {run.head_subject}
            </span>
          ) : null}
          <span className="ml-auto shrink-0">
            <StatusMark status={run.status} />
          </span>
        </span>

        <span className="mt-1.5 flex flex-wrap items-center gap-x-5 gap-y-2">
          <span className="font-mono text-[13px] text-paper-dim">
            {shortSha(run.base_sha)} → {shortSha(run.head_sha)}
          </span>

          <span className="ml-auto flex flex-wrap items-center gap-3">
            {run.findings_total === 0 ? (
              <span className="case-label">чисто</span>
            ) : (
              SEVERITY_ORDER.filter((severity) => counts[severity]).map((severity) => (
                <SeverityCount key={severity} severity={severity} count={counts[severity] ?? 0} />
              ))
            )}
            <span className="case-label">файлов {run.changed_files}</span>
          </span>
        </span>
      </Link>

      <DeleteCaseButton runId={run.id} repositoryId={run.repository_id} />
    </li>
  );
}

function SeverityCount({ severity, count }: { severity: Severity; count: number }) {
  return (
    <span className={`case-label ${SEVERITY_TEXT[severity]}`}>
      {SEVERITY_LABEL[severity]} <span className="tabular-nums">{count}</span>
    </span>
  );
}

interface NoticeProps {
  title: string;
  body: string;
  action?: { to: string; label: string };
}

function Notice({ title, body, action }: NoticeProps) {
  return (
    <div className="mx-auto max-w-lg py-20 text-center">
      <h2 className="font-display text-3xl font-semibold text-paper">{title}</h2>
      <p className="mt-3 text-[16px] text-paper-dim">{body}</p>
      {action ? (
        <Link
          to={action.to}
          className="mt-6 inline-block rounded-case border border-brass px-5 py-2 font-mono text-[13px] tracking-wide text-brass transition-colors hover:bg-brass hover:text-ink"
        >
          {action.label}
        </Link>
      ) : null}
    </div>
  );
}
