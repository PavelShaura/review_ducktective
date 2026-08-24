import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { ModelTrust } from "@/api/types";

const TRUST_HINT: Record<ModelTrust, string> = {
  local: "код не покидает машину",
  private_remote: "не учится на запросах",
  training_remote: "учится на запросах",
};

interface Props {
  repositoryId: string;
  value: string;
  onChange: (name: string) => void;
  compact?: boolean;
}

/**
 * Выбор модели для прогона или разговора.
 *
 * Список считается от политики репозитория, а не от всей установки:
 * предложить модель, а потом отказать при запуске — худший способ
 * объяснить правило. Пустое значение означает «пусть выберет роутер».
 */
export function ModelPicker({ repositoryId, value, onChange, compact = false }: Props) {
  const models = useQuery({
    queryKey: ["models", repositoryId],
    queryFn: () => api.listModels(repositoryId),
    enabled: Boolean(repositoryId),
  });

  if (!repositoryId || models.isPending || models.isError) {
    return null;
  }

  const chosen = models.data.find((model) => model.name === value);

  if (compact) {
    return (
      <label className="block space-y-1.5">
        <span className="case-label">модель</span>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-2 py-1.5 font-mono text-[12px] text-paper"
        >
          <option value="">по умолчанию</option>
          {models.data.map((model) => (
            <option key={model.name} value={model.name}>
              {model.name}
            </option>
          ))}
        </select>
        {chosen && chosen.trust === "training_remote" ? (
          <span className="block text-[11px] leading-snug text-major">
            учится на запросах: код останется у провайдера
          </span>
        ) : null}
      </label>
    );
  }

  return (
    <label className="block space-y-2">
      <span className="case-label">модель</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper"
      >
        <option value="">по умолчанию — выберет система</option>
        {models.data.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name} · {TRUST_HINT[model.trust]}
            {model.supports_tools ? "" : " · без инструментов"}
          </option>
        ))}
      </select>
      {chosen && chosen.trust === "training_remote" ? (
        <span className="block text-[13px] text-major">
          Эта модель учится на запросах: код уедет к провайдеру и останется у него.
        </span>
      ) : null}
      {models.data.length === 1 ? (
        <span className="block text-[13px] text-paper-dim">
          Доступна только локальная модель — политика репозитория не выпускает код
          наружу, либо удалённые не заведены.
        </span>
      ) : null}
    </label>
  );
}
