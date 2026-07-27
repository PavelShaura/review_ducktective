import { useState } from "react";

import type { Repository } from "@/api/types";

export interface NewRepositoryDraft {
  localPath: string;
  name: string;
  allowCloud: boolean;
}

interface Props {
  repositories: Repository[];
  selectedId: string;
  onSelect: (repositoryId: string) => void;
  draft: NewRepositoryDraft;
  onDraftChange: (draft: NewRepositoryDraft) => void;
  isAdding: boolean;
  onAddingChange: (isAdding: boolean) => void;
}

/** Выбор уже заведённого репозитория либо регистрация нового по пути. */
export function RepositoryPicker({
  repositories,
  selectedId,
  onSelect,
  draft,
  onDraftChange,
  isAdding,
  onAddingChange,
}: Props) {
  const hasRepositories = repositories.length > 0;
  const showForm = isAdding || !hasRepositories;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="case-label">репозиторий</span>
        {hasRepositories ? (
          <button
            type="button"
            onClick={() => onAddingChange(!isAdding)}
            className="font-mono text-[12px] text-paper-dim transition-colors hover:text-brass"
          >
            {isAdding ? "выбрать из списка" : "+ добавить по пути"}
          </button>
        ) : null}
      </div>

      {showForm ? (
        <NewRepositoryFields draft={draft} onChange={onDraftChange} />
      ) : (
        <select
          value={selectedId}
          onChange={(event) => onSelect(event.target.value)}
          required
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper"
        >
          <option value="" disabled>
            — выберите репозиторий —
          </option>
          {repositories.map((repository) => (
            <option key={repository.id} value={repository.id}>
              {repository.name} — {repository.local_path}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

interface FieldsProps {
  draft: NewRepositoryDraft;
  onChange: (draft: NewRepositoryDraft) => void;
}

function NewRepositoryFields({ draft, onChange }: FieldsProps) {
  const [isNameTouched, setIsNameTouched] = useState(false);

  const updatePath = (localPath: string) => {
    onChange({
      ...draft,
      localPath,
      name: isNameTouched ? draft.name : basename(localPath),
    });
  };

  return (
    <div className="space-y-3 border border-tweed-dim bg-ink-sunken p-3">
      <label className="block">
        <span className="case-label mb-1 block">путь к репозиторию</span>
        <input
          value={draft.localPath}
          onChange={(event) => updatePath(event.target.value)}
          placeholder="/home/user/projects/my-service"
          required
          spellCheck={false}
          className="w-full rounded-case border border-tweed-dim bg-ink px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
        />
        <span className="mt-1 block text-[13px] text-paper-dim">
          Путь на машине, где работает сервис, а не на вашей — если API запущен в контейнере,
          каталог должен быть примонтирован внутрь.
        </span>
      </label>

      <label className="block">
        <span className="case-label mb-1 block">название</span>
        <input
          value={draft.name}
          onChange={(event) => {
            setIsNameTouched(true);
            onChange({ ...draft, name: event.target.value });
          }}
          placeholder="my-service"
          required
          className="w-full rounded-case border border-tweed-dim bg-ink px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
        />
      </label>

      <label className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={draft.allowCloud}
          onChange={(event) => onChange({ ...draft, allowCloud: event.target.checked })}
          className="mt-1 accent-brass"
        />
        <span className="text-[14px] text-paper-dim">
          Разрешить облачные модели.
          <span className="block text-[13px]">
            По умолчанию код этого репозитория обрабатывается только локальной моделью.
          </span>
        </span>
      </label>
    </div>
  );
}

function basename(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] ?? "";
}
