import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api, ApiError } from "@/api/client";
import type { NewRepositoryDraft } from "@/components/RepositoryPicker";
import { IndexState } from "@/components/IndexState";
import { RepositoryPicker } from "@/components/RepositoryPicker";

const EMPTY_DRAFT: NewRepositoryDraft = { localPath: "", name: "", allowCloud: false };

export default function NewCasePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const repositories = useQuery({ queryKey: ["repositories"], queryFn: api.listRepositories });

  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [isAdding, setIsAdding] = useState(false);
  const [base, setBase] = useState("HEAD~1");
  const [head, setHead] = useState("HEAD");
  const [addedId, setAddedId] = useState("");

  const known = repositories.data ?? [];
  const isDraftMode = isAdding || known.length === 0;
  const isReady = isDraftMode ? draft.localPath.trim().length > 0 : selectedId.length > 0;
  const indexedId = isDraftMode ? addedId : selectedId;

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
      const run = await api.startReview(repositoryId, base, head);
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
        Укажите репозиторий и границы диффа. Ревью выполнит фоновый воркер, страница дела
        обновится сама.
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

        <div className="grid grid-cols-2 gap-4">
          <Field label="от ревизии">
            <TextInput value={base} onChange={setBase} placeholder="HEAD~1" />
          </Field>
          <Field label="до ревизии">
            <TextInput value={head} onChange={setHead} placeholder="HEAD" />
          </Field>
        </div>

        <button
          type="submit"
          disabled={start.isPending || !isReady}
          className="rounded-case border border-brass px-5 py-2 font-mono text-[13px] tracking-wide text-brass transition-colors hover:bg-brass hover:text-ink disabled:opacity-50"
        >
          {start.isPending ? "отправляю в работу…" : "начать расследование"}
        </button>

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
