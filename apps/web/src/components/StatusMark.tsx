import type { ReviewStatus } from "@/api/types";

const STATUS_LABEL: Record<ReviewStatus, string> = {
  queued: "в очереди",
  indexing: "индексация",
  running: "расследуется",
  completed: "закрыто",
  failed: "провалено",
  cancelled: "отозвано",
};

const STATUS_STYLE: Record<ReviewStatus, string> = {
  queued: "text-paper-dim",
  indexing: "text-minor",
  running: "text-brass",
  completed: "text-confirmed",
  failed: "text-critical",
  cancelled: "text-dismissed",
};

const IN_PROGRESS: ReviewStatus[] = ["queued", "indexing", "running"];

export function isInProgress(status: ReviewStatus): boolean {
  return IN_PROGRESS.includes(status);
}

export function StatusMark({ status }: { status: ReviewStatus }) {
  return (
    <span className={`case-label ${STATUS_STYLE[status]}`}>
      {isInProgress(status) ? (
        <span aria-hidden className="mr-1.5 inline-block animate-pulse">
          ●
        </span>
      ) : null}
      {STATUS_LABEL[status]}
    </span>
  );
}
