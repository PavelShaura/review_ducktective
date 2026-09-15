import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { ApiError, api } from "@/api/client";
import type { ModelPreset, ModelTrust, ProbeResult, ProviderConnection } from "@/api/types";
import { formatDateTime, formatNumber } from "@/lib/format";

const PRESET_KEYS = [
  "opencode-zen",
  "opencode-go",
  "openrouter-free",
  "groq",
  "gemini",
  "cerebras",
  "anthropic",
  "compatible",
] as const;

type PresetKey = (typeof PRESET_KEYS)[number];

function isKnownPreset(key: string): key is PresetKey {
  return (PRESET_KEYS as readonly string[]).includes(key);
}

/**
 * Текст пресета на языке интерфейса.
 *
 * Сервер описывает пресеты на своём языке; интерфейс знает их по ключу
 * и подписывает сам. Незнакомый ключ — новый пресет на сервере, о котором
 * словарь ещё не слышал, — показывается как прислан.
 */
function presetText(
  t: TFunction,
  preset: ModelPreset,
  field: "title" | "pricing" | "note",
): string {
  return isKnownPreset(preset.key) ? t(`presets.${preset.key}.${field}`) : preset[field];
}

/**
 * Заметка подключения на языке интерфейса.
 *
 * При заведении в подключение копируется заметка пресета — на языке
 * сервера. Если она совпадает с заметкой одного из пресетов, показывается
 * перевод; своя заметка остаётся как есть.
 */
function connectionNote(t: TFunction, note: string, presets: ModelPreset[]): string {
  const source = presets.find((preset) => preset.note === note);
  return source ? presetText(t, source, "note") : note;
}

const TRUST_CLASS: Record<ModelTrust, string> = {
  local: "trust-stamp trust-local",
  private_remote: "trust-stamp trust-private",
  training_remote: "trust-stamp trust-training",
};

/**
 * Подключения организации к провайдерам моделей.
 *
 * Единица здесь — подключение, а не модель: подписка даёт два десятка
 * моделей на один ключ, и заводить каждую руками значит заводить их заново
 * после каждого обновления у провайдера.
 */
export default function ModelsPage() {
  const { t } = useTranslation();
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const presets = useQuery({ queryKey: ["model-presets"], queryFn: api.listModelPresets });
  const [chosen, setChosen] = useState<ModelPreset | null>(null);

  if (connections.isPending || presets.isPending) {
    return <p className="case-label py-16 text-center">{t("models.loading")}</p>;
  }

  if (connections.isError || presets.isError) {
    return <p className="py-20 text-center text-paper-dim">{t("common.serviceDown")}</p>;
  }

  return (
    <div className="space-y-12">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">{t("models.title")}</h1>
        <p className="mt-3 max-w-3xl text-paper-dim">{t("models.intro")}</p>
      </header>

      <ConnectionList connections={connections.data} presets={presets.data} />

      <section className="space-y-4">
        <h2 className="font-display text-xl text-paper">{t("models.addTitle")}</h2>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {presets.data.map((preset) => (
            <li key={preset.key}>
              <button
                type="button"
                aria-pressed={chosen?.key === preset.key}
                onClick={() => setChosen(preset)}
                className="preset-card w-full"
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="preset-title">{presetText(t, preset, "title")}</span>
                  <span className={`${TRUST_CLASS[preset.trust]} shrink-0`}>
                    {t(`models.trustShort.${preset.trust}`)}
                  </span>
                </span>
                <span className="preset-pricing">{presetText(t, preset, "pricing")}</span>
              </button>
            </li>
          ))}
        </ul>
        {chosen ? (
          <AddConnectionForm key={chosen.key} preset={chosen} onDone={() => setChosen(null)} />
        ) : null}
      </section>
    </div>
  );
}

function ConnectionList({
  connections,
  presets,
}: {
  connections: ProviderConnection[];
  presets: ModelPreset[];
}) {
  const { t } = useTranslation();
  if (connections.length === 0) {
    return <p className="text-paper-dim">{t("models.none")}</p>;
  }

  return (
    <ul className="space-y-3">
      {connections.map((connection) => (
        <ConnectionCard key={connection.id} connection={connection} presets={presets} />
      ))}
    </ul>
  );
}

function ConnectionCard({
  connection,
  presets,
}: {
  connection: ProviderConnection;
  presets: ModelPreset[];
}) {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["connections"] });

  const toggle = useMutation({
    mutationFn: () => api.updateConnection(connection.id, { is_enabled: !connection.is_enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteConnection(connection.id),
    onSuccess: refresh,
  });
  const reload = useMutation({
    mutationFn: () => api.refreshCatalogue(connection.id),
    onSuccess: refresh,
  });
  const choose = useMutation({
    mutationFn: (model: string) => api.updateConnection(connection.id, { default_model: model }),
    onSuccess: refresh,
  });

  return (
    <li
      className={`rounded-case border bg-ink-raised ${
        connection.is_enabled ? "border-tweed-dim" : "border-tweed-dim/50 opacity-60"
      }`}
    >
      <div className="space-y-3 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-display text-lg text-paper">{connection.name}</span>
          <span className={TRUST_CLASS[connection.trust]}>
            {t(`models.trust.${connection.trust}`)}
          </span>
          <ConnectionStatus connection={connection} />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="fact-chip">
            {t("models.modelCount", { count: connection.models.length })}
          </span>
          <span className="fact-chip">{t("models.default", { model: connection.default_model })}</span>
          <span className="fact-chip">
            {connection.has_api_key ? t("models.keySet") : t("models.noKey")}
          </span>
          {connection.context_window ? (
            <span className="fact-chip">
              {t("models.window", { value: formatNumber(connection.context_window) })}
            </span>
          ) : null}
          {connection.catalogue_refreshed_at ? (
            <span className="fact-chip">
              {t("models.catalogueFrom", {
                date: formatDateTime(connection.catalogue_refreshed_at),
              })}
            </span>
          ) : null}
        </div>

        {connection.note ? (
          <p className="max-w-3xl text-[13px] leading-relaxed text-paper-dim">
            {connectionNote(t, connection.note, presets)}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button type="button" onClick={() => setIsOpen(!isOpen)} className="card-action">
            {isOpen
              ? t("models.hideModels")
              : t("models.showModels", { count: connection.models.length })}
          </button>
          <button
            type="button"
            disabled={reload.isPending}
            onClick={() => reload.mutate()}
            className="card-action card-action-primary"
          >
            {reload.isPending ? t("models.askingProvider") : t("models.refreshCatalogue")}
          </button>
          <button type="button" onClick={() => toggle.mutate()} className="card-action">
            {connection.is_enabled ? t("models.disable") : t("models.enable")}
          </button>
          <button
            type="button"
            onClick={() => remove.mutate()}
            className="card-action card-action-danger ml-auto"
          >
            {t("models.remove")}
          </button>
        </div>

        {reload.error ? <p className="text-critical">{describe(t, reload.error)}</p> : null}
      </div>

      {isOpen ? (
        <div className="border-t border-tweed-dim px-5 py-4">
          <p className="case-label mb-3">{t("models.asInPicker")}</p>
          <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
            {connection.models.map((model) => (
              <li key={model} className="flex items-center justify-between gap-2">
                <span
                  className={`truncate font-mono text-[13px] ${
                    model === connection.default_model ? "text-brass" : "text-paper-dim"
                  }`}
                >
                  {connection.name}/{model}
                </span>
                {model === connection.default_model ? (
                  <span className="case-label shrink-0">{t("models.isDefault")}</span>
                ) : (
                  <button
                    type="button"
                    disabled={choose.isPending}
                    onClick={() => choose.mutate(model)}
                    className="case-label shrink-0 text-paper-dim/60 hover:text-brass disabled:opacity-40"
                  >
                    {t("models.choose")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

/**
 * Состояние подключения: работает оно сейчас или отключено.
 *
 * Огонёк живой только у работающего — на карточке это единственное, что
 * движется, и взгляд находит его раньше остального текста. Подключение
 * без ключа тоже не работает, поэтому оно не «подключено», а ждёт ключа:
 * иначе зелёный горел бы там, где первый же вопрос упрётся в отказ.
 */
function ConnectionStatus({ connection }: { connection: ProviderConnection }) {
  const { t } = useTranslation();
  if (!connection.is_enabled) {
    return (
      <span className="status-badge status-off">
        <span className="status-dot" aria-hidden />
        {t("models.statusOff")}
      </span>
    );
  }

  if (!connection.has_api_key && connection.base_url === "") {
    return (
      <span className="status-badge status-off">
        <span className="status-dot" aria-hidden />
        {t("models.needsKey")}
      </span>
    );
  }

  return (
    <span className="status-badge status-live">
      <span className="status-dot" aria-hidden />
      {t("models.connected")}
    </span>
  );
}

/**
 * Заведение подключения: ключ и кнопка «проверить», остальное — по желанию.
 *
 * Форма перемонтируется на каждый пресет (`key` у вызывающего): иначе поля
 * держат значения предыдущего выбора, и адрес одного провайдера уезжает
 * к другому.
 */
function AddConnectionForm({ preset, onDone }: { preset: ModelPreset; onDone: () => void }) {
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [name, setName] = useState(preset.key);
  const [model, setModel] = useState(preset.model);
  const [baseUrl, setBaseUrl] = useState(preset.base_url);
  const [apiKey, setApiKey] = useState("");
  const [isDetailed, setIsDetailed] = useState(preset.key === "compatible");

  const probe = useMutation({
    mutationFn: () =>
      api.probeConnection({
        model: model.trim(),
        api_key: apiKey.trim(),
        provider: preset.provider,
        base_url: baseUrl.trim(),
      }),
    onSuccess: (result) => {
      const first = result.models[0];
      if (first && !result.models.includes(model.trim())) {
        setModel(first);
      }
    },
  });

  const add = useMutation({
    mutationFn: () =>
      api.addConnection({
        name: name.trim(),
        api_key: apiKey.trim(),
        default_model: model.trim(),
        catalogue: probe.data?.models ?? [],
        provider: preset.provider,
        base_url: baseUrl.trim(),
        trust: preset.trust,
        supports_tools: preset.supports_tools,
        context_window: preset.context_window,
        note: preset.note,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
      onDone();
    },
  });

  const offered = probe.data?.models ?? [];

  return (
    <div className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-6">
      <p className="text-paper-dim">
        {presetText(t, preset, "note")}
        {preset.signup_url ? (
          <>
            {" "}
            <a
              href={preset.signup_url}
              target="_blank"
              rel="noreferrer"
              className="text-brass underline-offset-2 hover:underline"
            >
              {t("models.getKey")}
            </a>
          </>
        ) : null}
      </p>

      <Field label={t("models.keyLabel")}>
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder={t("models.keyPlaceholder")}
          spellCheck={false}
          autoFocus
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
        />
      </Field>

      {offered.length > 0 ? (
        <Field label={t("models.defaultModelOffered", { count: offered.length })}>
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper"
          >
            {offered.map((identifier) => (
              <option key={identifier} value={identifier}>
                {identifier}
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={probe.isPending || !model.trim()}
          onClick={() => probe.mutate()}
          className="card-action"
        >
          {probe.isPending ? t("models.askingProvider") : t("models.probe")}
        </button>
        <button
          type="button"
          disabled={add.isPending || !name.trim() || !model.trim()}
          onClick={() => add.mutate()}
          className="card-action card-action-primary"
        >
          {add.isPending ? t("models.adding") : t("models.connect")}
        </button>
        <button type="button" onClick={onDone} className="card-action">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          onClick={() => setIsDetailed(!isDetailed)}
          className="card-action ml-auto"
        >
          {isDetailed ? t("models.hideDetails") : t("models.manual")}
        </button>
      </div>

      <ProbeVerdict result={probe.data} error={probe.error} />

      {isDetailed ? (
        <div className="space-y-4 border-t border-tweed-dim pt-4">
          <Field label={t("models.nameLabel")}>
            <TextInput value={name} onChange={setName} placeholder="go" />
          </Field>
          <Field label={t("models.defaultModel")}>
            <TextInput value={model} onChange={setModel} placeholder="kimi-k3" />
          </Field>
          <Field label={t("models.baseUrl")}>
            <TextInput value={baseUrl} onChange={setBaseUrl} placeholder="https://…/v1" />
          </Field>
        </div>
      ) : null}

      {add.error ? <p className="text-critical">{describe(t, add.error)}</p> : null}
    </div>
  );
}

/** Ответ провайдера словами: работает ключ или нет и что он предлагает. */
function ProbeVerdict({ result, error }: { result?: ProbeResult; error: unknown }) {
  const { t } = useTranslation();
  if (error) {
    return <p className="text-critical">{describe(t, error)}</p>;
  }
  if (!result) {
    return null;
  }
  if (!result.is_reachable) {
    return (
      <p className="border-l-2 border-critical bg-critical/5 px-3 py-2 text-[13px] text-paper">
        {t("models.providerDown", { detail: result.detail })}
      </p>
    );
  }
  return (
    <p className="border-l-2 border-confirmed bg-confirmed/5 px-3 py-2 text-[13px] text-paper">
      {result.models.length > 0
        ? t("models.probeListed", { count: result.models.length }) + t("models.allInPicker")
        : t("models.probeAnswered")}
    </p>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-2">
      <span className="case-label">{label}</span>
      {children}
    </label>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      spellCheck={false}
      className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
    />
  );
}

function describe(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) {
    return t("common.serviceDown");
  }
  return error.message;
}
