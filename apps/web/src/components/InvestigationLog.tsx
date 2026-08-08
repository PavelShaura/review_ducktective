import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { InvestigationStep, ReviewRun, StepKind } from "@/api/types";
import { isInProgress } from "@/components/StatusMark";

interface Props {
  run: ReviewRun;
}

const KIND_LABEL: Record<StepKind, string> = {
  thought: "рассуждает",
  tool_call: "запрос",
  tool_result: "ответ",
  answer: "итог",
  fallback: "без инструментов",
};

const KIND_TEXT: Record<StepKind, string> = {
  thought: "text-paper-dim",
  tool_call: "text-brass",
  tool_result: "text-paper",
  answer: "text-confirmed",
  fallback: "text-paper-dim",
};

/**
 * Ход расследования: что агент спросил у кодовой базы и что получил в ответ.
 *
 * Без этой ленты агентный режим неотличим от одноразового прохода: снаружи
 * видно только, что прогон стал дольше. Спорную находку тоже нечем ни
 * подтвердить, ни отклонить — цепочка вызовов и есть объяснение, откуда
 * взялся вывод.
 *
 * Идущий прогон читается потоком, законченный — одним запросом. Поток даёт
 * шаги в тот момент, когда они появляются, а у законченного дела появляться
 * уже нечему, и держать ради него сокет незачем.
 */
export function InvestigationLog({ run }: Props) {
  const isLive = isInProgress(run.status);
  const [streamed, setStreamed] = useState<InvestigationStep[]>([]);
  const seen = useRef(new Set<number>());

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

  if (steps.length === 0) {
    return null;
  }

  return (
    <section className="border border-tweed-dim bg-ink-raised">
      <header className="flex items-baseline justify-between border-b border-tweed-dim px-4 py-2">
        <h2 className="case-label text-brass">ход расследования</h2>
        <span className="case-label text-paper-dim">шагов: {steps.length}</span>
      </header>

      <ol className="max-h-96 space-y-1 overflow-y-auto px-4 py-3 font-mono text-xs">
        {steps.map((step) => (
          <StepLine key={step.cursor} step={step} />
        ))}
      </ol>
    </section>
  );
}

function StepLine({ step }: { step: InvestigationStep }) {
  const [isOpen, setOpen] = useState(false);
  const hasBody = step.detail.trim().length > 0;

  return (
    <li className="border-b border-tweed-dim/40 pb-1 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((open) => !open)}
        disabled={!hasBody}
        className="flex w-full items-baseline gap-2 text-left disabled:cursor-default"
      >
        <span className="w-8 shrink-0 text-paper-dim">{step.number}</span>
        <span className={`w-28 shrink-0 ${step.is_error ? "text-rejected" : KIND_TEXT[step.kind]}`}>
          {KIND_LABEL[step.kind]}
        </span>
        <span className="grow truncate text-paper-dim">{summarize(step)}</span>
        {step.duration_ms > 0 ? (
          <span className="shrink-0 text-paper-dim">{step.duration_ms} мс</span>
        ) : null}
      </button>

      {isOpen && hasBody ? (
        <pre className="mt-1 ml-10 whitespace-pre-wrap break-words text-paper-dim">
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
  return firstLine(step.detail) || step.file_path;
}

function firstLine(text: string): string {
  return text.split("\n").find((line) => line.trim().length > 0)?.trim() ?? "";
}
