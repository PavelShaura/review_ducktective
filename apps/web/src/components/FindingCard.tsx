import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { FeedbackVerdict, Finding } from "@/api/types";
import { FindingOrigin } from "@/components/FindingOrigin";
import {
  SEVERITY_BORDER,
  SEVERITY_LABEL,
  SEVERITY_NOTE,
  SEVERITY_TEXT,
} from "@/components/SeverityMark";
import { VerdictStamp } from "@/components/VerdictStamp";

interface Props {
  runId: string;
  finding: Finding;
}

export function FindingCard({ runId, finding }: Props) {
  const queryClient = useQueryClient();

  const feedback = useMutation({
    mutationFn: (verdict: FeedbackVerdict) =>
      api.submitFeedback(runId, finding.id, verdict),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  const verdict = finding.latest_verdict;

  return (
    <article
      className={`note-card ${SEVERITY_NOTE[finding.severity]} ${SEVERITY_BORDER[finding.severity]} ${
        finding.status === "rejected" ? "opacity-65" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-4 px-5 pt-3">
        <div className="min-w-0">
          <p className="case-label mb-1">
            <span className={SEVERITY_TEXT[finding.severity]}>
              {SEVERITY_LABEL[finding.severity]}
            </span>
            <span className="mx-2 opacity-40">·</span>
            <FindingOrigin
              category={finding.category}
              producerName={finding.producer_name}
            />
            <span className="mx-2 opacity-40">·</span>
            строки {finding.line_start}
            {finding.line_end === finding.line_start ? "" : `–${finding.line_end}`}
          </p>
          <h3 className="font-display text-[19px] leading-snug font-semibold text-paper">
            {finding.title}
          </h3>
        </div>
        {verdict ? <VerdictStamp verdict={verdict} /> : null}
      </div>

      <p className="px-5 pt-2 text-[15px] text-paper/85">{finding.body_markdown}</p>

      {finding.suggested_patch ? (
        <pre className="mx-4 mt-3 overflow-x-auto border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[13px] text-paper/90">
          <code>{finding.suggested_patch}</code>
        </pre>
      ) : null}

      <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-tweed-dim px-5 py-2.5">
        <VerdictButton
          label="Подтвердить"
          active={verdict === "useful"}
          activeClass="text-confirmed"
          disabled={feedback.isPending}
          onClick={() => feedback.mutate("useful")}
        />
        <VerdictButton
          label="Ложный след"
          active={verdict === "false_positive"}
          activeClass="text-dismissed"
          disabled={feedback.isPending}
          onClick={() => feedback.mutate("false_positive")}
        />
        <VerdictButton
          label="Отложить"
          active={verdict === "wontfix"}
          activeClass="text-minor"
          disabled={feedback.isPending}
          onClick={() => feedback.mutate("wontfix")}
        />

        {finding.confidence === null ? null : (
          <span className="case-label ml-auto">
            уверенность {Math.round(finding.confidence * 100)}%
          </span>
        )}
      </footer>

      {feedback.isError ? (
        <p className="px-5 pb-3 font-mono text-[12px] text-critical">
          Оценка не сохранилась. Проверьте, что сервис доступен, и повторите.
        </p>
      ) : null}
    </article>
  );
}

interface ButtonProps {
  label: string;
  active: boolean;
  activeClass: string;
  disabled: boolean;
  onClick: () => void;
}

function VerdictButton({ label, active, activeClass, disabled, onClick }: ButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={`verdict-button px-4 py-2 font-mono text-[13px] tracking-wide disabled:opacity-50 ${
        active ? `verdict-button-active ${activeClass}` : ""
      }`}
    >
      {label}
    </button>
  );
}
