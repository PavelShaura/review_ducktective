import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import { formatDateTime } from "@/lib/format";

interface Props {
  repositoryId: string;
  chosenId: string;
  onChoose: (id: string) => void;
  onStart: () => void;
  isStarting: boolean;
  reusedHint: boolean;
}

/**
 * Разговоры по репозиторию, свежие сверху.
 *
 * Заголовком служит первый вопрос: до него разговор ещё ни о чём, и просить
 * человека придумать название значит просить его угадать, о чём выйдет беседа.
 */
export function ConversationList({
  repositoryId,
  chosenId,
  onChoose,
  onStart,
  isStarting,
  reusedHint,
}: Props) {
  const queryClient = useQueryClient();

  const conversations = useQuery({
    queryKey: ["conversations", repositoryId],
    queryFn: () => api.listConversations(repositoryId),
  });

  const remove = useMutation({
    mutationFn: (conversationId: string) => api.deleteConversation(conversationId),
    onSuccess: (_, conversationId) => {
      if (conversationId === chosenId) {
        onChoose("");
      }
      void queryClient.invalidateQueries({ queryKey: ["conversations", repositoryId] });
    },
  });

  return (
    <aside className="flex h-full min-h-0 flex-col gap-3">
      <button type="button" onClick={onStart} disabled={isStarting} className="action-brass w-full">
        {isStarting ? "завожу…" : "+ новый разговор"}
      </button>

      {reusedHint ? (
        <p className="rounded-case border border-brass-dim bg-brass/10 px-3 py-2 text-[13px] text-brass">
          Этот разговор уже заведён и пока пуст — задайте вопрос в нём.
        </p>
      ) : null}

      <p className="case-label px-1">разговоров: {conversations.data?.length ?? 0}</p>

      {conversations.data?.length === 0 ? (
        <p className="rounded-case border border-dashed border-tweed-dim px-3 py-4 text-[13px] text-paper-dim">
          Разговоров ещё не было. Заведите первый — история сохранится.
        </p>
      ) : null}

      <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {conversations.data?.map((conversation) => (
          <li key={conversation.id} className="flex items-stretch gap-2">
            <button
              type="button"
              aria-current={conversation.id === chosenId}
              onClick={() => onChoose(conversation.id)}
              className="thread-card min-w-0 flex-1"
            >
              <span className="line-clamp-2 text-[13px] leading-snug">
                {conversation.title || "без вопроса"}
              </span>
              <span className="mt-2 flex items-center justify-between gap-2">
                <span className="case-label">{formatDateTime(conversation.updated_at)}</span>
                <span className="thread-count">{conversation.message_count}</span>
              </span>
            </button>
            <button
              type="button"
              title="удалить разговор"
              aria-label="удалить разговор"
              onClick={() => remove.mutate(conversation.id)}
              className="thread-remove self-start"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
