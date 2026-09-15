import { currentLocale, i18next } from "@/i18n";

const STAGED_REVISION = "staged";

export function shortSha(value: string): string {
  if (value === STAGED_REVISION) {
    return i18next.t("format.stagedRevision");
  }
  return value.slice(0, 8);
}

/** Дата в формате языка интерфейса: он задаёт и порядок дня с месяцем. */
export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString(currentLocale(), {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatNumber(value: number): string {
  return value.toLocaleString(currentLocale());
}

export function formatTokens(input: number, output: number): string {
  return `${formatNumber(input)} → ${formatNumber(output)}`;
}
