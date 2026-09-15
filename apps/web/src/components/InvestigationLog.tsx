import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { InvestigationStep, ReviewRun, StepKind } from "@/api/types";
import { isInProgress } from "@/components/StatusMark";

interface Props {
  run: ReviewRun;
}

const KIND_TEXT: Record<StepKind, string> = {
  stage: "text-brass",
  thought: "text-paper-dim",
  tool_call: "text-brass",
  tool_result: "text-paper",
  answer: "text-confirmed",
  fallback: "text-paper-dim",
};

/**
 * Ход расследования: чем прогон занят и что агент спросил у кодовой базы.
 *
 * Панель показывается с первой секунды идущего дела, ещё до первого шага:
 * пустое место под счётчиком времени не отвечает на единственный вопрос,
 * который у человека есть, — работа идёт или встала.
 *
 * Лента ограничена пятью строками и прокручивается к последнему шагу:
 * за прогон набираются десятки обращений, и во весь рост она отодвигала
 * дифф за экран. Свёрнутая оставляет одну строку — что происходит сейчас.
 *
 * Файл назван в каждой строке, потому что лента общая на прогон, а шаги
 * приходят от разных файлов вперемешку: без имени «готово, замечаний 0»
 * читается как конец всего дела, а не как конец одного файла.
 */
export function InvestigationLog({ run }: Props) {
  const { t } = useTranslation();
  const isLive = isInProgress(run.status);
  const [isOpen, setIsOpen] = useState(true);
  const [streamed, setStreamed] = useState<InvestigationStep[]>([]);
  const seen = useRef(new Set<number>());
  const tail = useRef<HTMLLIElement | null>(null);

  const settled = useQuery({
    queryKey: ["investigation", run.id],
    queryFn: () => api.getInvestigation(run.id),
    enabled: !isLive,
  });

  useEffect(() => {
    if (!isLive) {
      return;
    }

    const socket = api.investigationStream(run.id);
    socket.onmessage = (event) => {
      const step = JSON.parse(event.data as string) as InvestigationStep;
      if (seen.current.has(step.cursor)) {
        return;
      }
      seen.current.add(step.cursor);
      setStreamed((previous) => [...previous, step]);
    };

    return () => socket.close();
  }, [isLive, run.id]);

  const steps = isLive ? streamed : (settled.data?.steps ?? []);

  useEffect(() => {
    if (isLive && isOpen) {
      tail.current?.scrollIntoView({ block: "nearest" });
    }
  }, [isLive, isOpen, steps.length]);

  if (!isLive && steps.length === 0) {
    return null;
  }

  const current = steps[steps.length - 1];

  return (
    <section className="border border-tweed-dim bg-ink-raised">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        className={`flex w-full items-baseline gap-3 px-4 py-2 text-left ${
          isOpen ? "border-b border-tweed-dim" : ""
        }`}
      >
        <span aria-hidden className="font-mono text-[13px] text-paper-dim">
          {isOpen ? "▾" : "▸"}
        </span>
        <h2 className="case-label text-brass">{t("investigation.title")}</h2>
        <span className="case-label ml-auto text-paper-dim">
          {t("investigation.steps", { count: steps.length })}
        </span>
      </button>

      {!isOpen && isLive && current ? (
        <p className="truncate px-4 py-2 text-[13px] text-paper-dim">
          <span className="text-brass">{t("investigation.now")}</span>
          {summarize(current)}
        </p>
      ) : null}

      {isOpen ? (
        <>
          {isLive ? (
            <p className="border-b border-tweed-dim px-4 py-3 text-paper">
              {current ? (
                <>
                  <span className="text-brass">{t("investigation.now")}</span>
                  {summarize(current)}
                  {current.file_path ? (
                    <span className="text-paper-dim">
                      {" "}
                      · {shortPath(current.file_path)}
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="text-paper-dim">
                  {t("investigation.loading")}
                </span>
              )}
            </p>
          ) : null}

          <ol className="investigation-steps space-y-1 overflow-y-auto px-4 py-3 font-mono text-xs">
            {steps.map((step) => (
              <StepLine key={step.cursor} step={step} />
            ))}
            <li ref={tail} />
          </ol>
        </>
      ) : null}
    </section>
  );
}

function StepLine({ step }: { step: InvestigationStep }) {
  const [isOpen, setOpen] = useState(false);
  const { t } = useTranslation();
  const hasBody = step.detail.trim().length > 0 && step.kind !== "stage";

  return (
    <li className="border-b border-tweed-dim/40 pb-1 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((open) => !open)}
        disabled={!hasBody}
        className="flex w-full items-baseline gap-2 text-left disabled:cursor-default"
      >
        <span
          className={`w-24 shrink-0 ${step.is_error ? "text-rejected" : KIND_TEXT[step.kind]}`}
        >
          {t(`investigation.kind.${step.kind}`)}
        </span>
        <span
          className="w-40 shrink-0 truncate text-paper-dim"
          title={step.file_path || undefined}
        >
          {shortPath(step.file_path)}
        </span>
        <span className="grow truncate text-paper">{summarize(step)}</span>
        {step.duration_ms > 0 ? (
          <span className="shrink-0 text-paper-dim">
            {t("investigation.ms", { value: step.duration_ms })}
          </span>
        ) : null}
      </button>

      {isOpen && hasBody ? (
        <pre className="mt-1 ml-26 whitespace-pre-wrap break-words text-paper-dim">
          {step.detail}
        </pre>
      ) : null}
    </li>
  );
}

/**
 * Строка, по которой шаг узнаётся не разворачивая.
 *
 * У запроса это его аргументы: по ним видно, о чём агент спросил, а сам
 * ответ нужен уже при разборе спорной находки.
 */
function summarize(step: InvestigationStep): string {
  if (step.kind === "tool_call") {
    return `${step.tool_name ?? ""}(${step.arguments ?? ""})`;
  }
  if (step.kind === "tool_result") {
    return `${step.tool_name ?? ""} · ${firstLine(step.detail)}`;
  }
  return firstLine(step.detail) || shortPath(step.file_path);
}

function shortPath(path: string): string {
  if (!path) {
    return "—";
  }
  const parts = path.split("/");
  return parts.length <= 2 ? path : `…/${parts.slice(-2).join("/")}`;
}

function firstLine(text: string): string {
  return (
    text
      .split("\n")
      .find((line) => line.trim().length > 0)
      ?.trim() ?? ""
  );
}
