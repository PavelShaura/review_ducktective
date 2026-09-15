import { useTranslation } from "react-i18next";

import type { Severity } from "@/api/types";

export const SEVERITY_TEXT: Record<Severity, string> = {
  critical: "text-critical",
  major: "text-major",
  minor: "text-minor",
  nitpick: "text-nitpick",
};

export const SEVERITY_BORDER: Record<Severity, string> = {
  critical: "border-l-critical",
  major: "border-l-major",
  minor: "border-l-minor",
  nitpick: "border-l-nitpick",
};

/** Тонировка плашки замечания под её уровень. */
export const SEVERITY_NOTE: Record<Severity, string> = {
  critical: "note-critical",
  major: "note-major",
  minor: "note-minor",
  nitpick: "note-nitpick",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor", "nitpick"];

interface Props {
  severity: Severity;
  count?: number;
}

/** Метка уровня: засечка цвета и подпись, без иконок и бейджей. */
export function SeverityMark({ severity, count }: Props) {
  const { t } = useTranslation();
  return (
    <span className={`case-label inline-flex items-center gap-1.5 ${SEVERITY_TEXT[severity]}`}>
      <span aria-hidden className="inline-block h-2.5 w-0.5 bg-current" />
      {t(`severity.${severity}`)}
      {count === undefined ? null : <span className="tabular-nums">{count}</span>}
    </span>
  );
}
