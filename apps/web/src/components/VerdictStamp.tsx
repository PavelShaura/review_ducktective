import type { FeedbackVerdict } from "@/api/types";

export const VERDICT_ORDER: FeedbackVerdict[] = ["useful", "false_positive", "wontfix"];

export const VERDICT_LABEL: Record<FeedbackVerdict, string> = {
  useful: "подтверждено",
  false_positive: "ложный след",
  wontfix: "отложено",
};

export const VERDICT_TEXT: Record<FeedbackVerdict, string> = {
  useful: "text-confirmed",
  false_positive: "text-dismissed",
  wontfix: "text-minor",
};

interface Props {
  verdict: FeedbackVerdict;
}

/** Оттиск вердикта на карточке находки — визуальный итог разметки. */
export function VerdictStamp({ verdict }: Props) {
  return (
    <span className={`stamp text-[12px] ${VERDICT_TEXT[verdict]}`}>
      {VERDICT_LABEL[verdict]}
    </span>
  );
}
