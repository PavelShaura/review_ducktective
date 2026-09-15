import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { ApiError, api } from "@/api/client";
import type { LogFilter, LogLevel, LogRecord, LogTail } from "@/api/types";
import { currentLocale } from "@/i18n";

const LIVE_INTERVAL_MS = 3000;
const TYPING_PAUSE_MS = 400;

const LEVELS: (LogLevel | null)[] = [null, "debug", "info", "warning", "error"];

const LIMITS = [100, 200, 500, 1000];

/** Цвет уровня — как у серьёзности находок: одна шкала тревоги на весь интерфейс. */
const LEVEL_TEXT: Record<string, string> = {
  debug: "text-nitpick",
  info: "text-minor",
  warning: "text-major",
  error: "text-critical",
  critical: "text-critical",
};

const DEFAULT_FILTER: LogFilter = { limit: 200, level: null, logger: "", q: "" };

/**
 * Журнал установки: хвост файла, в который пишут api и воркеры.
 *
 * Читается по запросу, а не потоком: администратор приходит сюда разобраться
 * с уже случившимся, и страница, которая сама уезжает вниз, только мешает.
 * Живое обновление включается отдельно — на время, пока смотришь прогон.
 */
export default function LogsPage() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<LogFilter>(DEFAULT_FILTER);
  const [isLive, setIsLive] = useState(false);
  const applied = useDebounced(filter, TYPING_PAUSE_MS);

  const tail = useQuery({
    queryKey: ["logs", applied],
    queryFn: () => api.tailLogs(applied),
    refetchInterval: isLive ? LIVE_INTERVAL_MS : false,
    placeholderData: (previous) => previous,
    retry: false,
  });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">{t("logs.title")}</h1>
        <p className="mt-2 max-w-2xl text-[15px] text-paper-dim">{t("logs.intro")}</p>
      </header>

      <Filters
        filter={filter}
        onChange={setFilter}
        isLive={isLive}
        onLiveChange={setIsLive}
        isFetching={tail.isFetching}
        onRefresh={() => void tail.refetch()}
      />

      {tail.isPending ? (
        <p className="case-label py-16 text-center">{t("logs.opening")}</p>
      ) : tail.isError ? (
        <p className="border border-tweed-dim bg-ink-raised px-5 py-6 text-[15px] text-paper-dim">
          {describeError(t, tail.error)}
        </p>
      ) : (
        <>
          <Summary tail={tail.data} />
          {tail.data.records.length === 0 ? (
            <p className="border border-tweed-dim bg-ink-raised px-5 py-6 text-[15px] text-paper-dim">
              {t("logs.noMatch")}
            </p>
          ) : (
            <ol className="space-y-1">
              {tail.data.records.map((record, index) => (
                <LogRow key={`${record.timestamp ?? ""}-${index}`} record={record} />
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

interface FiltersProps {
  filter: LogFilter;
  onChange: (filter: LogFilter) => void;
  isLive: boolean;
  onLiveChange: (isLive: boolean) => void;
  isFetching: boolean;
  onRefresh: () => void;
}

function Filters({ filter, onChange, isLive, onLiveChange, isFetching, onRefresh }: FiltersProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-end gap-3 border border-tweed-dim bg-ink-raised px-5 py-4">
      <label className="space-y-2">
        <span className="case-label">{t("logs.level")}</span>
        <select
          value={filter.level ?? ""}
          onChange={(event) =>
            onChange({ ...filter, level: (event.target.value || null) as LogLevel | null })
          }
          className={INPUT_CLASS}
        >
          {LEVELS.map((level) => (
            <option key={level ?? "all"} value={level ?? ""}>
              {level ? t("logs.levelFrom", { level }) : t("logs.levelAll")}
            </option>
          ))}
        </select>
      </label>

      <label className="min-w-48 space-y-2">
        <span className="case-label">{t("logs.logger")}</span>
        <input
          value={filter.logger}
          onChange={(event) => onChange({ ...filter, logger: event.target.value })}
          placeholder="ducktective.reviewer"
          spellCheck={false}
          className={INPUT_CLASS}
        />
      </label>

      <label className="min-w-64 flex-1 space-y-2">
        <span className="case-label">{t("logs.search")}</span>
        <input
          value={filter.q}
          onChange={(event) => onChange({ ...filter, q: event.target.value })}
          placeholder={t("logs.searchPlaceholder")}
          spellCheck={false}
          className={INPUT_CLASS}
        />
      </label>

      <label className="space-y-2">
        <span className="case-label">{t("logs.records")}</span>
        <select
          value={filter.limit}
          onChange={(event) => onChange({ ...filter, limit: Number(event.target.value) })}
          className={INPUT_CLASS}
        >
          {LIMITS.map((limit) => (
            <option key={limit} value={limit}>
              {limit}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        onClick={() => onLiveChange(!isLive)}
        aria-pressed={isLive}
        className={`case-label rounded-case border px-4 py-2 ${
          isLive ? "border-brass text-brass" : "border-tweed-dim text-paper hover:text-brass"
        }`}
        title={t("logs.liveTitle")}
      >
        {isLive ? t("logs.liveOn") : t("logs.liveOff")}
      </button>

      <button
        type="button"
        onClick={onRefresh}
        disabled={isFetching}
        className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
      >
        {isFetching ? t("logs.reading") : t("logs.refresh")}
      </button>
    </div>
  );
}

const INPUT_CLASS =
  "w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50";

/**
 * Значение, отстающее от ввода на паузу в наборе.
 *
 * Журнал перечитывается с диска на каждый запрос; без паузы каждая буква
 * в поле поиска поднимала бы файл заново.
 */
function useDebounced<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}

function Summary({ tail }: { tail: LogTail }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[13px] text-paper-dim">
      <span className="truncate" title={tail.file}>
        {tail.file}
      </span>
      <span className="opacity-40">·</span>
      <span>{formatBytes(t, tail.size_bytes)}</span>
      <span className="opacity-40">·</span>
      <span>
        {t("logs.shown")} <span className="tabular-nums text-paper">{tail.records.length}</span>
        {tail.truncated ? t("logs.truncated") : ""}
      </span>
      {tail.skipped_lines > 0 ? (
        <span className="text-major">
          {t("logs.skipped")}
          <span className="tabular-nums">{tail.skipped_lines}</span>
        </span>
      ) : null}
    </div>
  );
}

function LogRow({ record }: { record: LogRecord }) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const fields = Object.entries(record.fields);
  const hasDetails = record.exception !== null || fields.length > 0;
  const level = record.level ?? "—";

  return (
    <li
      className={`rounded-case border border-tweed-dim bg-ink-raised transition-colors ${
        hasDetails ? "hover:border-brass" : ""
      }`}
    >
      <button
        type="button"
        onClick={() => hasDetails && setIsOpen((open) => !open)}
        className={`flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 text-left ${
          hasDetails ? "cursor-pointer" : "cursor-default"
        }`}
      >
        <span className="shrink-0 font-mono text-[12px] tabular-nums text-paper-dim">
          {formatTimestamp(record.timestamp)}
        </span>
        <span className={`case-label w-16 shrink-0 ${LEVEL_TEXT[level] ?? ""}`}>{level}</span>
        <span className="shrink-0 font-mono text-[12px] text-tweed">{record.logger ?? "—"}</span>
        <span className="min-w-0 flex-1 truncate text-[14px] text-paper">{record.event}</span>
        {hasDetails ? (
          <span className="case-label shrink-0 text-paper-dim/60">
            {isOpen ? t("common.collapse") : "…"}
          </span>
        ) : null}
      </button>

      {isOpen ? (
        <div className="space-y-2 border-t border-tweed-dim px-4 py-3">
          {fields.length > 0 ? (
            <dl className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[12px]">
              {fields.map(([key, value]) => (
                <div key={key} className="flex gap-1">
                  <dt className="text-paper-dim">{key}=</dt>
                  <dd className="text-paper">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {record.exception ? (
            <pre className="overflow-x-auto whitespace-pre-wrap border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[12px] text-critical">
              {record.exception}
            </pre>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function formatTimestamp(value: string | null): string {
  if (value === null) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(currentLocale(), {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function formatBytes(t: TFunction, size: number): string {
  if (size < 1024) return t("logs.bytes", { value: size });
  if (size < 1024 * 1024) return t("logs.kilobytes", { value: (size / 1024).toFixed(1) });
  return t("logs.megabytes", { value: (size / (1024 * 1024)).toFixed(1) });
}

function describeError(t: TFunction, error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return t("logs.forbidden");
    }
    return error.message;
  }
  return t("logs.unavailable");
}
