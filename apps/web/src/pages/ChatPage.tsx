import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { ConversationList } from "@/components/ConversationList";
import { ConversationView } from "@/components/ConversationView";
import { IndexAction, IndexBadge } from "@/components/IndexBadge";
import { ModelPicker } from "@/components/ModelPicker";

/**
 * Разговор о проиндексированном репозитории.
 *
 * Всё, что не сам разговор — выбор репозитория, состояние индекса, модель
 * и список бесед, — собрано в узкую панель слева: раньше это тремя плашками
 * во всю ширину отталкивало вниз то, ради чего страницу открывают, и на
 * чтение ответа оставалась треть экрана.
 *
 * Репозиторий выбирается первым и на весь разговор: беседа опирается
 * на его индекс, и сменить его посреди значит оставить историю, которая
 * говорит о чужом коде.
 */
export default function ChatPage() {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [repositoryId, setRepositoryId] = useState<string>("");
  const [model, setModel] = useState("");
  const [conversationId, setConversationId] = useState<string>("");
  const [isReused, setIsReused] = useState(false);

  const repositories = useQuery({
    queryKey: ["repositories"],
    queryFn: api.listRepositories,
  });

  const index = useQuery({
    queryKey: ["index", repositoryId],
    queryFn: () => api.getIndexState(repositoryId),
    enabled: Boolean(repositoryId),
  });

  const chosen = repositories.data?.find((item) => item.id === repositoryId);

  const start = useMutation({
    mutationFn: () => api.startConversation(repositoryId, model || undefined),
    onSuccess: (started) => {
      setConversationId(started.conversation.id);
      setIsReused(!started.isNew);
      void queryClient.invalidateQueries({ queryKey: ["conversations", repositoryId] });
    },
  });

  if (repositories.isPending) {
    return <p className="case-label py-16 text-center">{t("chat.loading")}</p>;
  }

  if (repositories.isError) {
    return <p className="py-20 text-center text-paper-dim">{t("common.serviceDown")}</p>;
  }

  if (repositories.data.length === 0) {
    return <p className="py-20 text-center text-paper-dim">{t("chat.nothingToTalk")}</p>;
  }

  return (
    <div className="grid h-[calc(100vh-11rem)] min-h-[34rem] gap-5 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
      <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
        <label className="block space-y-1.5">
          <span className="case-label">{t("chat.repository")}</span>
          <select
            value={repositoryId}
            onChange={(event) => {
              setRepositoryId(event.target.value);
              setConversationId("");
            }}
            className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-2 py-1.5 font-mono text-[13px] text-paper"
          >
            <option value="">{t("chat.choose")}</option>
            {repositories.data.map((repository) => (
              <option key={repository.id} value={repository.id}>
                {repository.name}
              </option>
            ))}
          </select>
        </label>

        {repositoryId ? (
          <div className="flex flex-col items-start gap-1.5">
            <IndexBadge repositoryId={repositoryId} />
            <IndexAction repositoryId={repositoryId} />
          </div>
        ) : null}

        {repositoryId ? (
          <ModelPicker repositoryId={repositoryId} value={model} onChange={setModel} compact />
        ) : null}

        {repositoryId ? (
          <div className="min-h-0 flex-1">
            <ConversationList
              repositoryId={repositoryId}
              chosenId={conversationId}
              onChoose={(id) => {
                setConversationId(id);
                setIsReused(false);
              }}
              onStart={() => start.mutate()}
              isStarting={start.isPending}
              reusedHint={isReused}
            />
          </div>
        ) : null}
      </aside>

      {conversationId ? (
        <ConversationView
          key={conversationId}
          conversationId={conversationId}
          repositoryName={chosen?.name ?? ""}
          isIndexReady={index.data?.context_ready ?? false}
        />
      ) : (
        <EmptyState hasRepository={Boolean(repositoryId)} />
      )}
    </div>
  );
}

/**
 * Что видно, пока разговор не открыт.
 *
 * Здесь же живёт объяснение, зачем эта вкладка: заголовок с абзацем текста
 * над разговором съедал бы высоту у ответа на каждом вопросе, а нужен он
 * ровно один раз — в первый.
 */
function EmptyState({ hasRepository }: { hasRepository: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-case border border-dashed border-tweed-dim px-6 py-16 text-center">
      <p className="font-display text-2xl text-paper">{t("chat.emptyTitle")}</p>
      <p className="max-w-md text-[14px] leading-relaxed text-paper-dim">{t("chat.emptyBody")}</p>
      <p className="case-label mt-2">
        {hasRepository ? t("chat.openOrNew") : t("chat.chooseLeft")}
      </p>
    </div>
  );
}
