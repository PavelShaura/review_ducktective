import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { ChatEvent, ChatMessage } from "@/api/types";
import { Answer } from "@/components/Answer";
import { DocumentAttachment } from "@/components/DocumentAttachment";
import { ToolCard } from "@/components/ToolCard";
import { useChatSocket } from "@/lib/useChatSocket";

interface Props {
  conversationId: string;
  repositoryName: string;
  isIndexReady: boolean;
}

interface LivePiece {
  kind: "thought" | "answer" | "note" | "failure";
  text: string;
}

interface LiveTool {
  callId: string;
  name: string;
  arguments: string;
  result: string;
}

type LiveItem = ({ tool: LiveTool } & { kind: "tool" }) | ({ kind: LivePiece["kind"] } & LivePiece);

/**
 * Один разговор: история из базы плюс то, что приходит прямо сейчас.
 *
 * Пока ответ пишется, показывается поток; как только он дописан, разговор
 * перечитывается из базы и живые куски уступают место записанным. Так на
 * экране не остаётся двух версий одного ответа.
 */
export function ConversationView({ conversationId, repositoryName, isIndexReady }: Props) {
  const queryClient = useQueryClient();
  const [live, setLive] = useState<LiveItem[]>([]);
  const [asked, setAsked] = useState<string>("");
  const [isAnswering, setIsAnswering] = useState(false);
  const tail = useRef<HTMLDivElement | null>(null);

  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.getConversation(conversationId),
  });

  /**
   * Убирает живые куски, когда ответ дописан.
   *
   * Отказ так не убирается: за ним в базе может не быть ничего — вопрос
   * к непроиндексированному репозиторию отклоняется до записи, — и уборка
   * стирает и вопрос, и объяснение, оставляя пустой экран вместо причины.
   */
  const settle = useCallback(
    (isAnswered: boolean) => {
      setIsAnswering(false);
      void queryClient
        .invalidateQueries({ queryKey: ["conversation", conversationId] })
        .then(() => {
          if (isAnswered) {
            setAsked("");
            setLive([]);
          }
        });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    [conversationId, queryClient],
  );

  const socket = useChatSocket(conversationId, {
    onEvent: (event) => {
      setLive((previous) => absorb(previous, event));
      if (event.kind === "answer" || event.kind === "failure") {
        settle(event.kind === "answer");
      }
    },
    onReconnect: () => settle(true),
  });

  useEffect(() => {
    tail.current?.scrollIntoView({ block: "nearest" });
  }, [live.length, conversation.data?.messages.length]);

  const stored = conversation.data?.messages ?? [];
  const isStoredAlready = stored.at(-1)?.role === "user" && stored.at(-1)?.content === asked;
  const pending = isStoredAlready ? "" : asked;

  const isEmpty = !pending && live.length === 0 && !isAnswering && stored.length === 0;

  const ask = (question: string) => {
    socket.ask(question);
    setAsked(question);
    setLive([]);
    setIsAnswering(true);
  };

  return (
    <section className="flex h-full min-h-0 flex-col rounded-case border border-tweed-dim bg-ink-sunken">
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {stored.map((message) => (
          <StoredMessage key={message.id} message={message} />
        ))}

        {pending ? <Bubble side="user">{pending}</Bubble> : null}

        {live.map((item, index) =>
          item.kind === "tool" ? (
            <ToolCard
              key={`${item.tool.callId}-${index}`}
              name={item.tool.name}
              arguments={item.tool.arguments}
              result={item.tool.result}
            />
          ) : (
            <LiveBubble key={index} piece={item} />
          ),
        )}

        {isAnswering && live.length === 0 ? <p className="case-label">думаю над ответом…</p> : null}

        {isEmpty ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-12 text-center">
            <p className="font-display text-lg text-paper">Разговор пуст</p>
            <p className="max-w-md text-[13px] text-paper-dim">
              Спросите о коде {repositoryName} своими словами — точное имя знать не нужно.
            </p>
          </div>
        ) : null}

        <div ref={tail} />
      </div>

      <div className="border-t border-tweed-dim px-5 py-3">
        <DocumentAttachment
          conversationId={conversationId}
          document={conversation.data?.document ?? null}
        />
      </div>

      <Composer
        repositoryName={repositoryName}
        isAnswering={isAnswering}
        isReconnecting={socket.connection === "connecting"}
        isIndexReady={isIndexReady}
        onAsk={ask}
      />
    </section>
  );
}

function absorb(items: LiveItem[], event: ChatEvent): LiveItem[] {
  if (event.kind === "token") {
    const last = items[items.length - 1];
    if (last && last.kind === "answer") {
      return [...items.slice(0, -1), { kind: "answer", text: last.text + event.text }];
    }
    return [...items, { kind: "answer", text: event.text }];
  }

  if (event.kind === "note") {
    return [...items, { kind: "note", text: event.text }];
  }

  if (event.kind === "failure") {
    return [...items, { kind: "failure", text: event.text }];
  }

  if (event.kind === "tool_call") {
    const closed = closeDraft(items);
    return [
      ...closed,
      {
        kind: "tool",
        tool: {
          callId: event.tool_call_id ?? "",
          name: event.tool_name ?? "",
          arguments: event.tool_arguments ?? "",
          result: "",
        },
      },
    ];
  }

  if (event.kind === "tool_result") {
    return items.map((item) =>
      item.kind === "tool" && item.tool.callId === event.tool_call_id && !item.tool.result
        ? { kind: "tool", tool: { ...item.tool, result: event.text } }
        : item,
    );
  }

  return items;
}

/**
 * Закрывает начатый ответ, когда агент пошёл смотреть код.
 *
 * Сказанное перед вызовом инструмента — это рассуждение по пути, а не итог,
 * и оставлять его в том же пузыре, куда потом придёт ответ, значит склеить
 * черновик с выводом.
 */
function closeDraft(items: LiveItem[]): LiveItem[] {
  const last = items[items.length - 1];
  if (!last || last.kind !== "answer") {
    return items;
  }
  if (!last.text.trim()) {
    return items.slice(0, -1);
  }
  return [...items.slice(0, -1), { kind: "thought", text: last.text }];
}

function StoredMessage({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return <Bubble side="user">{message.content}</Bubble>;
  }

  if (message.role === "tool") {
    return <ToolCard name={message.tool_name ?? ""} arguments="" result={message.content} />;
  }

  if (message.tool_calls.length > 0) {
    return (
      <>
        {message.content.trim() ? <Thought text={message.content} /> : null}
        {message.tool_calls.map((call) => (
          <ToolCard key={call.call_id} name={call.name} arguments={call.arguments} result="" />
        ))}
      </>
    );
  }

  return (
    <Bubble
      side="agent"
      footer={message.model ? `${message.model} · ${message.tokens_output} т.` : ""}
    >
      <Answer text={message.content} />
    </Bubble>
  );
}

function LiveBubble({ piece }: { piece: LivePiece }) {
  if (piece.kind === "note") {
    return <p className="case-label">{piece.text}</p>;
  }
  if (piece.kind === "failure") {
    return (
      <p className="border-l-2 border-critical bg-critical/5 px-3 py-2 text-[14px] text-paper">
        {piece.text}
      </p>
    );
  }
  if (piece.kind === "thought") {
    return <Thought text={piece.text} />;
  }
  return (
    <Bubble side="agent">
      <Answer text={piece.text} />
    </Bubble>
  );
}

function Thought({ text }: { text: string }) {
  return <p className="border-l-2 border-tweed pl-3 text-[13px] italic text-paper-dim">{text}</p>;
}

interface BubbleProps {
  side: "user" | "agent";
  footer?: string;
  children: React.ReactNode;
}

function Bubble({ side, footer, children }: BubbleProps) {
  const isUser = side === "user";
  return (
    <div className={isUser ? "flex justify-end" : ""}>
      <div
        className={`max-w-[46rem] px-4 py-3 text-[14px] leading-relaxed text-paper ${
          isUser ? "bubble-user whitespace-pre-wrap" : "bubble-agent"
        }`}
      >
        {children}
        {footer ? <span className="case-label mt-2 block">{footer}</span> : null}
      </div>
    </div>
  );
}

interface ComposerProps {
  repositoryName: string;
  isAnswering: boolean;
  isReconnecting: boolean;
  isIndexReady: boolean;
  onAsk: (question: string) => void;
}

/**
 * Поле вопроса.
 *
 * Заблокировано только пока пишется ответ: на время потери связи вопрос
 * принимается и ждёт восстановления. Заблокированное поле без объяснения
 * человек читает как поломку, а не как ожидание.
 */
function Composer({
  repositoryName,
  isAnswering,
  isReconnecting,
  isIndexReady,
  onAsk,
}: ComposerProps) {
  const [text, setText] = useState("");

  const send = () => {
    const question = text.trim();
    if (!question || isAnswering || !isIndexReady) {
      return;
    }
    onAsk(question);
    setText("");
  };

  return (
    <form
      className="space-y-2 border-t border-tweed-dim px-5 py-4"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      {isIndexReady ? null : (
        <p className="border-l-2 border-critical bg-critical/5 px-3 py-2 text-[13px] text-paper">
          Репозиторий не проиндексирован — разговор идёт по индексу, и смотреть в код агенту нечем.
          Нажмите «проиндексировать» в блоке индекса выше.
        </p>
      )}

      {isReconnecting ? (
        <p className="case-label text-brass">связь восстанавливается — вопрос уйдёт следом</p>
      ) : null}
      <div className="flex items-end gap-3">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          rows={2}
          placeholder={`вопрос о коде ${repositoryName}`}
          className="composer-input flex-1 resize-none rounded-case border border-tweed bg-transparent px-3 py-2 text-[14px] text-paper focus:border-brass focus:outline-none"
        />
        <button
          type="submit"
          disabled={isAnswering || !isIndexReady || !text.trim()}
          className="action-brass"
        >
          {isAnswering ? "отвечает…" : "спросить"}
        </button>
      </div>
    </form>
  );
}
