const STAGED_REVISION = "staged";

export function shortSha(value: string): string {
  if (value === STAGED_REVISION) {
    return "индекс";
  }
  return value.slice(0, 8);
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTokens(input: number, output: number): string {
  return `${input.toLocaleString("ru-RU")} → ${output.toLocaleString("ru-RU")}`;
}
