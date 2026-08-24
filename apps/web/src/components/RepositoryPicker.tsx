import { useState } from "react";

import type { EgressPolicy, Repository } from "@/api/types";

export interface NewRepositoryDraft {
  localPath: string;
  name: string;
  egressPolicy: EgressPolicy;
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

/**
 * Поля новой записи: путь, название и то, куда разрешено уезжать коду.
 *
 * Вынесены наружу, потому что репозиторий заводят из двух мест — перед
 * первым ревью и со страницы индексов, — а спрашивать одно и то же
 * по-разному значит завести две правды об одном.
 */
export function NewRepositoryFields({ draft, onChange }: FieldsProps) {
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

      <fieldset className="space-y-2">
        <legend className="case-label mb-1">куда разрешено уезжать коду</legend>
        {EGRESS_CHOICES.map((choice) => (
          <label key={choice.value} className="flex items-start gap-2.5">
            <input
              type="radio"
              name="egress-policy"
              checked={draft.egressPolicy === choice.value}
              onChange={() => onChange({ ...draft, egressPolicy: choice.value })}
              className="mt-1 accent-brass"
            />
            <span className="text-[14px] text-paper-dim">
              {choice.title}
              <span className="block text-[13px]">{choice.explanation}</span>
            </span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}

/**
 * Три уровня вместо галочки «можно облако».
 *
 * Разница между провайдером, обещавшим не учиться на запросах, и бесплатным
 * маршрутом, который такого не обещает, — это в точности та разница, ради
 * которой политика заведена. Стереть её галочкой значит стереть весь смысл.
 */
const EGRESS_CHOICES: {
  value: EgressPolicy;
  title: string;
  explanation: string;
}[] = [
  {
    value: "local_only",
    title: "Только локальная модель",
    explanation: "Код не покидает машину. Подходит для кода под NDA.",
  },
  {
    value: "allow_cloud",
    title: "Удалённые модели с обязательством не обучаться",
    explanation:
      "Платные провайдеры, обещающие не хранить и не использовать запросы для обучения.",
  },
  {
    value: "allow_training_cloud",
    title: "Любые удалённые, включая бесплатные",
    explanation:
      "Бесплатные тиры логируют запросы и учатся на них. Годится для открытого кода и проб.",
  },
];

function basename(path: string): string {
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] ?? "";
}
