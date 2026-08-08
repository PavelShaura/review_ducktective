import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api, ApiError } from "@/api/client";
import type { IndexState as IndexStateData } from "@/api/types";
import type { NewRepositoryDraft } from "@/components/RepositoryPicker";
import { IndexState } from "@/components/IndexState";
import { RepositoryPicker } from "@/components/RepositoryPicker";
import { shortSha } from "@/lib/format";

const EMPTY_DRAFT: NewRepositoryDraft = { localPath: "", name: "", allowCloud: false };

export default function NewCasePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const repositories = useQuery({ queryKey: ["repositories"], queryFn: api.listRepositories });

  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [isAdding, setIsAdding] = useState(false);
  const [mode, setMode] = useState<DiffMode>("commit");
  const [commit, setCommit] = useState("HEAD");
  const [base, setBase] = useState("HEAD~1");
  const [head, setHead] = useState("HEAD");
  const [addedId, setAddedId] = useState("");

  const known = repositories.data ?? [];
  const isDraftMode = isAdding || known.length === 0;
  const isReady = isDraftMode ? draft.localPath.trim().length > 0 : selectedId.length > 0;
  const indexedId = isDraftMode ? addedId : selectedId;

  /* Тот же ключ, что у панели индекса: значение берётся из кэша,
     второго запроса за состоянием не уходит. */
  const index = useQuery({
    queryKey: ["index", indexedId],
    queryFn: () => api.getIndexState(indexedId),
    enabled: false,
  });

  /* Репозиторий заводится отдельно от прогона: без него нечего индексировать,
     а собрать индекс разумно до первого ревью, а не после. */
  const add = useMutation({
    mutationFn: () => registerDraft(draft),
    onSuccess: async (repositoryId) => {
      setAddedId(repositoryId);
      setSelectedId(repositoryId);
      setIsAdding(false);
      await queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
  });

  const start = useMutation({
    mutationFn: async () => {
      const repositoryId = isDraftMode ? await registerDraft(draft) : selectedId;
      const range = revisionRange(mode, { commit, base, head });
      const run = await api.startReview(repositoryId, range.base, range.head);
      await api.enqueueReview(run.id);
      return run;
    },
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: ["repositories"] });
      navigate(`/cases/${run.id}`);
    },
  });

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-4xl font-semibold text-paper">Завести дело</h1>
      <p className="mt-2 text-[16px] text-paper-dim">
        Укажите репозиторий и что смотреть: один коммит целиком или диапазон ревизий.
        Ревью выполнит фоновый воркер, страница дела обновится сама.
      </p>

      <form
        className="mt-8 space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          start.mutate();
        }}
      >
        <RepositoryPicker
          repositories={known}
          selectedId={selectedId}
          onSelect={setSelectedId}
          draft={draft}
          onDraftChange={setDraft}
          isAdding={isAdding}
          onAddingChange={setIsAdding}
        />

        {isDraftMode ? (
          <AddRepositoryHint
            isReady={draft.localPath.trim().length > 0}
            isPending={add.isPending}
            onAdd={() => add.mutate()}
          />
        ) : null}

        {indexedId ? <IndexState repositoryId={indexedId} /> : null}

        <ModePicker mode={mode} onChange={setMode} />

        {mode === "commit" ? (
          <Field label="коммит">
            <TextInput
              value={commit}
              onChange={setCommit}
              placeholder="784418ca23a или HEAD"
            />
          </Field>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <Field label="от ревизии">
              <TextInput
                value={base}
                onChange={setBase}
                placeholder="HEAD~1"
              />
            </Field>
            <Field label="до ревизии">
              <TextInput
                value={head}
                onChange={setHead}
                placeholder="HEAD"
              />
            </Field>
          </div>
        )}

        <StaleIndexWarning
          state={index.data}
          head={revisionRange(mode, { commit, base, head }).head}
          repositoryId={indexedId}
        />

        <button
          type="submit"
          disabled={start.isPending || !isReady}
          className="rounded-case border border-brass px-5 py-2 font-mono text-[13px] tracking-wide text-brass transition-colors hover:bg-brass hover:text-ink disabled:opacity-50"
        >
          {start.isPending ? "отправляю в работу…" : "начать расследование"}
        </button>

        <ContextWarning state={index.data} />

        {start.isError ? (
          <p className="border-l-2 border-critical bg-critical/5 px-3 py-2 text-[14px] text-paper">
            {describeError(start.error)}
          </p>
        ) : null}
      </form>
    </div>
  );
}

async function registerDraft(draft: NewRepositoryDraft): Promise<string> {
  const repository = await api.registerRepository(
    draft.localPath.trim(),
    draft.name.trim(),
    draft.allowCloud,
  );
  return repository.id;
}

interface AddRepositoryHintProps {
  isReady: boolean;
  isPending: boolean;
  onAdd: () => void;
}

/**
 * Предложение завести репозиторий до запуска ревью.
 *
 * Индекс строится только для заведённого репозитория, а собирать его после
 * первого прогона поздно: этот прогон уже пройдёт без окружения.
 */
function AddRepositoryHint({ isReady, isPending, onAdd }: AddRepositoryHintProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-tweed-dim bg-ink-sunken px-4 py-3">
      <span className="text-[14px] text-paper-dim">
        Проиндексировать проект.
      </span>
      <button
        type="button"
        onClick={onAdd}
        disabled={!isReady || isPending}
        className="ml-auto rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] tracking-wide text-paper-dim transition-colors hover:border-brass hover:text-brass disabled:opacity-40"
      >
        {isPending ? "завожу…" : "завести репозиторий"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="case-label mb-1.5 block">{label}</span>
      {children}
    </label>
  );
}

interface TextInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}

function TextInput({ value, onChange, placeholder }: TextInputProps) {
  return (
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      required
      spellCheck={false}
      className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
    />
  );
}

function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Не удалось начать ревью. Проверьте, что API и воркер запущены.";
  }
  if (error.status === 409) {
    return "Репозиторий с таким названием уже заведён — выберите его из списка.";
  }
  if (error.status === 422) {
    return "Между указанными ревизиями нет изменений.";
  }
  return error.message;
}


interface ContextWarningProps {
  state: IndexStateData | undefined;
}

/**
 * Чем обернётся запуск ревью прямо сейчас.
 *
 * Идущая сборка расследованию не мешает и его не задерживает: окружение
 * берётся из последнего завершённого снапшота, а не из собираемого. Но если
 * завершённого нет, ревью пойдёт по одному диффу и найдёт заметно меньше —
 * об этом человек должен узнать до нажатия, а не из результата.
 */
function ContextWarning({ state }: ContextWarningProps) {
  const building = state?.status === "pending" || state?.status === "running";
  if (!building) {
    return null;
  }

  if (state?.context_ready) {
    return (
      <p className="border-l-2 border-tweed-dim px-3 py-2 text-[13px] text-paper-dim">
        Индекс пересобирается — расследованию это не мешает. Окружение возьмётся
        из прошлой сборки, новое подхватят следующие дела.
      </p>
    );
  }

  return (
    <p className="border-l-2 border-brass bg-brass/5 px-3 py-2 text-[13px] text-paper">
      Индекс ещё собирается, и готового окружения пока нет: расследование пройдёт
      по одному диффу и найдёт заметно меньше. Дождитесь конца сборки, если важна полнота.
    </p>
  );
}


/**
 * Индекс собран не на той ревизии, которую собираются ревьюить.
 *
 * Прогон от этого не ломается — инструменты уходят на git и читают нужный
 * коммит, — но теряют граф вызовов: в индексе с другой ревизии изменённых
 * символов нет вовсе. Сказать об этом надо до запуска, а не в ленте
 * расследования, где уже поздно.
 *
 * Ревизию разрешает сервер, а не сравнение строк: `HEAD`, имя ветки
 * и `abc123~1` — ссылки, и во что они указывают, знает только git. Сравнивая
 * их со строкой из базы, форма сообщала о расхождении там, где его не было.
 *
 * Пока индекс собирается, сообщения нет: ревизия ещё меняется, а вторая
 * поставленная в очередь сборка мешает первой.
 *
 * Сказано как факт о том, что произойдёт, а не как упрёк: в поле может стоять
 * подстановка `HEAD`, которую человек и не выбирал, а знать про отсутствие
 * графа ему всё равно нужно — до запуска, а не после.
 */
function StaleIndexWarning({
  state,
  head,
  repositoryId,
}: {
  state: IndexStateData | undefined;
  head: string;
  repositoryId: string;
}) {
  const queryClient = useQueryClient();
  const isSettled =
    Boolean(state?.is_ready) && state?.status !== "running" && state?.status !== "pending";

  const resolved = useQuery({
    queryKey: ["revision", repositoryId, head],
    queryFn: () => api.resolveRevision(repositoryId, head),
    enabled: isSettled && head.trim().length > 0,
    retry: false,
  });

  const reindex = useMutation({
    mutationFn: () => api.startIndexing(repositoryId, head),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["index", repositoryId] }),
  });

  const indexed = state?.commit_sha;
  const wanted = resolved.data?.commit_sha;
  if (!isSettled || !indexed || !wanted || indexed === wanted) {
    return null;
  }

  return (
    <p className="border border-tweed-dim bg-ink-raised px-4 py-3 text-paper-dim">
      Ревью пойдёт по {shortSha(wanted)}
      {head.trim() === wanted ? "" : ` (${head.trim()})`}, а индекс собран на{" "}
      {shortSha(indexed)}. Инструменты прочитают нужный коммит через git — без графа
      вызовов.{" "}
      <button
        type="button"
        onClick={() => reindex.mutate()}
        disabled={reindex.isPending}
        className="text-brass underline-offset-2 hover:underline disabled:opacity-50"
      >
        {reindex.isPending ? "ставлю в очередь…" : `проиндексировать ${shortSha(wanted)}`}
      </button>
    </p>
  );
}

type DiffMode = "commit" | "range";

/**
 * Что именно ревьюим: один коммит или диапазон.
 *
 * Коммит стоит первым и выбран по умолчанию, потому что это обычный случай:
 * человек смотрит свой pull request и знает его хеш, а границы диапазона
 * ему приходится выдумывать.
 */
function ModePicker({ mode, onChange }: { mode: DiffMode; onChange: (mode: DiffMode) => void }) {
  const options: Array<{ value: DiffMode; label: string }> = [
    { value: "commit", label: "один коммит" },
    { value: "range", label: "диапазон ревизий" },
  ];

  return (
    <div className="flex gap-2">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={`rounded-case border px-3 py-1 font-mono text-[12px] tracking-wide transition-colors ${
            mode === option.value
              ? "border-brass text-brass"
              : "border-tweed-dim text-paper-dim hover:text-paper"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Границы диффа для выбранного режима.
 *
 * Один коммит разворачивается в пару «его родитель → он сам»: сервер и так
 * разрешает относительные ссылки в полные хеши, поэтому отдельного вида
 * запроса для этого не нужно. У первого коммита в истории родителя нет,
 * и git объяснит это внятнее, чем смогла бы проверка здесь.
 */
function revisionRange(
  mode: DiffMode,
  values: { commit: string; base: string; head: string },
): { base: string; head: string } {
  if (mode === "range") {
    return { base: values.base, head: values.head };
  }

  const commit = values.commit.trim() || "HEAD";
  return { base: `${commit}~1`, head: commit };
}
