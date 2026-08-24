import { useState } from "react";

import { ToolCard } from "@/components/ToolCard";

export interface TrailTool {
  callId: string;
  name: string;
  arguments: string;
  result: string;
}

interface Props {
  tools: TrailTool[];
  isLive: boolean;
}

/**
 * Путь агента по кодовой базе — свёрнутый в одну строку.
 *
 * Разговор о большом репозитории стоит десятка обращений, и каждое своей
 * карточкой вытесняло с экрана то, ради чего спрашивали: ответ. Здесь они
 * сложены в одну строку, которая раскрывается, когда источники нужно
 * проверить, — а проверить их должно быть можно, иначе утверждение о чужом
 * коде нечем подтвердить.
 *
 * Пока ответ идёт, показывается последнее обращение: свёрнутая строка
 * с растущим счётчиком выглядит как зависание, а видеть, чем занят агент,
 * важнее краткости ровно в эту минуту.
 */
export function ToolTrail({ tools, isLive }: Props) {
  const [isOpen, setIsOpen] = useState(false);

  if (tools.length === 0) {
    return null;
  }

  if (tools.length === 1 && !isLive) {
    const only = tools[0]!;
    return (
      <ToolCard name={only.name} arguments={only.arguments} result={only.result} dense />
    );
  }

  const current = tools[tools.length - 1]!;

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setIsOpen((previous) => !previous)}
        className="trail-summary"
      >
        <span className="trail-count">{tools.length}</span>
        <span className="truncate">
          {isLive ? "спрашивает кодовую базу" : "обращений к кодовой базе"}
        </span>
        <span className="ml-auto shrink-0 text-paper-dim/70">
          {isOpen ? "свернуть −" : "показать +"}
        </span>
      </button>

      {isOpen ? (
        <div className="space-y-1 border-l border-tweed-dim pl-3">
          {tools.map((tool, index) => (
            <ToolCard
              key={`${tool.callId}-${index}`}
              name={tool.name}
              arguments={tool.arguments}
              result={tool.result}
              dense
            />
          ))}
        </div>
      ) : isLive ? (
        <ToolCard
          name={current.name}
          arguments={current.arguments}
          result={current.result}
          dense
        />
      ) : null}
    </div>
  );
}
