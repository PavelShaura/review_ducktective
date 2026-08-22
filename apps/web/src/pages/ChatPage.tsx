import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import type { Repository } from "@/api/types";
import { ConversationList } from "@/components/ConversationList";
import { ConversationView } from "@/components/ConversationView";
import { IndexState } from "@/components/IndexState";

/**
 * Разговор о проиндексированном репозитории.
 *
 * Репозиторий выбирается первым и на весь разговор: беседа опирается
 * на его индекс, и сменить его посреди значит оставить историю, которая
 * говорит о чужом коде.
 */
export default function ChatPage() {
  const queryClient = useQueryClient();
  const [repositoryId, setRepositoryId] = useState<string>("");
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
    mutationFn: () => api.startConversation(repositoryId),
    onSuccess: (started) => {
      setConversationId(started.conversation.id);
      setIsReused(!started.isNew);
      void queryClient.invalidateQueries({ queryKey: ["conversations", repositoryId] });
    },
  });

  if (repositories.isPending) {
    return <p className="case-label py-16 text-center">поднимаю картотеку…</p>;
  }

  if (repositories.isError) {
    return <p className="py-20 text-center text-paper-dim">Сервис не отвечает.</p>;
  }

  if (repositories.data.length === 0) {
    return (
      <p className="py-20 text-center text-paper-dim">
        Говорить пока не о чем: ни одного репозитория не заведено.
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">Чат по кодовой базе</h1>
        <p className="mt-2 max-w-2xl text-[15px] text-paper-dim">
          Спрашивайте своими словами — точное имя знать не нужно. Агент ищет по смыслу, читает
          определения и смотрит, кто что вызывает, и отвечает со ссылками на файлы и строки.
          Отвечает он по индексу, то есть по зафиксированной ревизии.
        </p>
      </header>

      <RepositoryChoice
        repositories={repositories.data}
        chosenId={repositoryId}
        onChoose={(id) => {
          setRepositoryId(id);
          setConversationId("");
        }}
      />

      {repositoryId ? <IndexState repositoryId={repositoryId} /> : null}

      {repositoryId ? (
        <div className="grid h-[68vh] min-h-[30rem] gap-6 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
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
          {conversationId ? (
            <ConversationView
              key={conversationId}
              conversationId={conversationId}
              repositoryName={chosen?.name ?? ""}
              isIndexReady={index.data?.context_ready ?? false}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 rounded-case border border-dashed border-tweed-dim px-6 py-16 text-center">
              <p className="font-display text-xl text-paper">Разговор не выбран</p>
              <p className="max-w-md text-[14px] text-paper-dim">
                Откройте прошлый слева или заведите новый — и спрашивайте своими словами: «где
                проверяются права?», «что делает этот пак?», «кто это вызывает?»
              </p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

interface ChoiceProps {
  repositories: Repository[];
  chosenId: string;
  onChoose: (id: string) => void;
}

function RepositoryChoice({ repositories, chosenId, onChoose }: ChoiceProps) {
  return (
    <div className="space-y-2">
      <p className="case-label">о каком репозитории говорим</p>
      <div className="flex flex-wrap gap-2">
        {repositories.map((repository) => (
          <button
            key={repository.id}
            type="button"
            aria-pressed={repository.id === chosenId}
            onClick={() => onChoose(repository.id)}
            className="repo-tab"
          >
            {repository.name}
          </button>
        ))}
      </div>
    </div>
  );
}
