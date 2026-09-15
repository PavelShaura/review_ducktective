import { useTranslation } from "react-i18next";

import type { ReviewStatus } from "@/api/types";

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
  const { t } = useTranslation();
  return (
    <span className={`case-label ${STATUS_STYLE[status]}`}>
      {isInProgress(status) ? (
        <span aria-hidden className="mr-1.5 inline-block animate-pulse">
          ●
        </span>
      ) : null}
      {t(`status.${status}`)}
    </span>
  );
}
