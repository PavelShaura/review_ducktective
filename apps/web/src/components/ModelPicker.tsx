import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

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
  const { t } = useTranslation();
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
        <span className="case-label">{t("modelPicker.label")}</span>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-2 py-1.5 font-mono text-[12px] text-paper"
        >
          <option value="">{t("modelPicker.default")}</option>
          {models.data.map((model) => (
            <option key={model.name} value={model.name}>
              {model.name}
            </option>
          ))}
        </select>
        {chosen && chosen.trust === "training_remote" ? (
          <span className="block text-[11px] leading-snug text-major">
            {t("modelPicker.trainingShort")}
          </span>
        ) : chosen && chosen.trust === "private_remote" ? (
          <span className="block text-[11px] leading-snug text-paper-dim">
            {t("modelPicker.remoteShort")}
          </span>
        ) : null}
      </label>
    );
  }

  return (
    <label className="block space-y-2">
      <span className="case-label">{t("modelPicker.label")}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper"
      >
        <option value="">{t("modelPicker.defaultLong")}</option>
        {models.data.map((model) => (
          <option key={model.name} value={model.name}>
            {model.name} · {t(`modelPicker.trust.${model.trust}`)}
            {model.supports_tools ? "" : t("modelPicker.noTools")}
          </option>
        ))}
      </select>
      {chosen && chosen.trust === "training_remote" ? (
        <span className="block text-[13px] text-major">{t("modelPicker.trainingLong")}</span>
      ) : chosen && chosen.trust === "private_remote" ? (
        <span className="block text-[13px] text-paper-dim">{t("modelPicker.remoteLong")}</span>
      ) : null}
      {models.data.length === 1 ? (
        <span className="block text-[13px] text-paper-dim">
          {t("modelPicker.onlyLocal")}
        </span>
      ) : null}
    </label>
  );
}
