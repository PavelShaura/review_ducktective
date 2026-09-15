import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { ApiError, api } from "@/api/client";
import type { Repository } from "@/api/types";
import { IndexAction, IndexBadge } from "@/components/IndexBadge";
import { IndexState } from "@/components/IndexState";
import { NewRepositoryFields } from "@/components/RepositoryPicker";
import type { NewRepositoryDraft } from "@/components/RepositoryPicker";
import { shortSha } from "@/lib/format";

const EMPTY_DRAFT: NewRepositoryDraft = {
  localPath: "",
  name: "",
  egressPolicy: "local_only",
};

/**
 * Индексы всех репозиториев организации в одном месте.
 *
 * До этой страницы состояние индекса было видно только внутри дела или
 * разговора — то есть тогда, когда уже поздно: собирать его приходят
 * заранее, а спрашивают «а что вообще собрано» отдельно от всего.
 */
export default function IndexesPage() {
  const { t } = useTranslation();
  const repositories = useQuery({
    queryKey: ["repositories"],
    queryFn: api.listRepositories,
  });

  if (repositories.isPending) {
    return <p className="case-label py-16 text-center">{t("indexes.loading")}</p>;
  }

  if (repositories.isError) {
    return <p className="py-20 text-center text-paper-dim">{t("common.serviceDown")}</p>;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">{t("indexes.title")}</h1>
        <p className="mt-3 max-w-3xl text-paper-dim">{t("indexes.intro")}</p>
      </header>

      {repositories.data.length === 0 ? (
        <p className="text-paper-dim">{t("indexes.none")}</p>
      ) : (
        <ul className="space-y-3">
          {repositories.data.map((repository) => (
            <IndexRow key={repository.id} repository={repository} />
          ))}
        </ul>
      )}

      <AddRepository isFirst={repositories.data.length === 0} />
    </div>
  );
}

/**
 * Заведение репозитория прямо здесь — вместе с первой сборкой индекса.
 *
 * Раньше репозиторий заводили только перед ревью, а индекс собирали потом
 * и в другом месте. Но приходят сюда именно за этим: «вот каталог, разберите
 * его», — и разводить два шага по двум страницам значит требовать знания
 * порядка, которого никто не обещал.
 */
function AddRepository({ isFirst }: { isFirst: boolean }) {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(isFirst);
  const [draft, setDraft] = useState<NewRepositoryDraft>(EMPTY_DRAFT);

  const add = useMutation({
    mutationFn: async (withIndexing: boolean) => {
      const repository = await api.registerRepository(
        draft.localPath.trim(),
        draft.name.trim(),
        draft.egressPolicy,
      );
      if (withIndexing) {
        await api.startIndexing(repository.id);
      }
      return repository;
    },
    onSuccess: async (repository) => {
      setDraft(EMPTY_DRAFT);
      setIsOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["repositories"] });
      await queryClient.invalidateQueries({ queryKey: ["index", repository.id] });
    },
  });

  const isReady = draft.localPath.trim().length > 0 && draft.name.trim().length > 0;

  if (!isOpen) {
    return (
      <button type="button" onClick={() => setIsOpen(true)} className="card-action">
        {t("indexes.add")}
      </button>
    );
  }

  return (
    <section className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-5">
      <h2 className="font-display text-xl text-paper">{t("indexes.newTitle")}</h2>

      <NewRepositoryFields draft={draft} onChange={setDraft} />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!isReady || add.isPending}
          onClick={() => add.mutate(true)}
          className={`card-action card-action-primary ${add.isPending ? "card-action-busy" : ""}`}
        >
          {add.isPending ? t("indexes.adding") : t("indexes.addAndIndex")}
        </button>
        <button
          type="button"
          disabled={!isReady || add.isPending}
          onClick={() => add.mutate(false)}
          className="card-action"
        >
          {t("indexes.addOnly")}
        </button>
        <button
          type="button"
          onClick={() => {
            setDraft(EMPTY_DRAFT);
            setIsOpen(false);
          }}
          className="card-action ml-auto"
        >
          {t("common.cancel")}
        </button>
      </div>

      {add.error ? <p className="text-critical">{describe(t, add.error)}</p> : null}
    </section>
  );
}

function describe(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) {
    return t("common.serviceDown");
  }
  if (error.status === 409) {
    return t("indexes.conflict");
  }
  if (error.status === 422) {
    return error.message;
  }
  return error.message;
}

function IndexRow({ repository }: { repository: Repository }) {
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useTranslation();

  const state = useQuery({
    queryKey: ["index", repository.id],
    queryFn: () => api.getIndexState(repository.id),
  });

  const totals = state.data?.totals;

  return (
    <li className="rounded-case border border-tweed-dim bg-ink-raised">
      <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">
        <span className="min-w-0 space-y-2">
          <span className="flex flex-wrap items-center gap-3">
            <span className="font-display text-lg text-paper">{repository.name}</span>
            <IndexBadge repositoryId={repository.id} />
          </span>
          <span className="flex flex-wrap items-center gap-2">
            {state.data?.commit_sha ? (
              <span className="fact-chip">
                {t("indexes.revision", { sha: shortSha(state.data.commit_sha) })}
              </span>
            ) : null}
            {totals?.files ? (
              <span className="fact-chip">{t("indexes.symbols", { count: totals.symbols })}</span>
            ) : null}
            {totals?.files ? (
              <span className="fact-chip">{t("indexes.chunks", { count: totals.chunks })}</span>
            ) : null}
            {totals?.files ? (
              <span className="fact-chip">{t("indexes.edges", { count: totals.edges })}</span>
            ) : null}
            <span className="fact-chip">{repository.local_path}</span>
          </span>
        </span>

        <span className="flex shrink-0 items-center gap-2">
          <IndexAction repositoryId={repository.id} />
          <button type="button" onClick={() => setIsOpen(!isOpen)} className="card-action">
            {isOpen ? t("common.collapse") : t("indexes.details")}
          </button>
        </span>
      </div>

      {isOpen ? (
        <div className="border-t border-tweed-dim px-5 py-4">
          <IndexState repositoryId={repository.id} />
        </div>
      ) : null}
    </li>
  );
}
