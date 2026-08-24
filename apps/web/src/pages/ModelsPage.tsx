import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/api/client";
import type { ModelPreset, ModelTrust, ProbeResult, ProviderConnection } from "@/api/types";
import { formatDateTime } from "@/lib/format";

const TRUST_LABEL: Record<ModelTrust, string> = {
  local: "локальная",
  private_remote: "не учится на запросах",
  training_remote: "учится на запросах",
};

const TRUST_CLASS: Record<ModelTrust, string> = {
  local: "trust-stamp trust-local",
  private_remote: "trust-stamp trust-private",
  training_remote: "trust-stamp trust-training",
};

/** То же самое короче: на плитке рядом с названием длинная подпись не встаёт. */
const TRUST_SHORT: Record<ModelTrust, string> = {
  local: "локально",
  private_remote: "не учится",
  training_remote: "учится",
};

/**
 * Подключения организации к провайдерам моделей.
 *
 * Единица здесь — подключение, а не модель: подписка даёт два десятка
 * моделей на один ключ, и заводить каждую руками значит заводить их заново
 * после каждого обновления у провайдера.
 */
export default function ModelsPage() {
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const presets = useQuery({ queryKey: ["model-presets"], queryFn: api.listModelPresets });
  const [chosen, setChosen] = useState<ModelPreset | null>(null);

  if (connections.isPending || presets.isPending) {
    return <p className="case-label py-16 text-center">достаю картотеку моделей…</p>;
  }

  if (connections.isError || presets.isError) {
    return <p className="py-20 text-center text-paper-dim">Сервис не отвечает.</p>;
  }

  return (
    <div className="space-y-12">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">Модели</h1>
        <p className="mt-3 max-w-3xl text-paper-dim">
          Локальная модель настроена на сервере и доступна всегда. Удалённые приходят
          подключениями: один ключ — все модели провайдера, и выбрать любую можно
          при запуске ревью или разговора. Ключ хранится зашифрованным и обратно
          не показывается.
        </p>
      </header>

      <ConnectionList connections={connections.data} />

      <section className="space-y-4">
        <h2 className="font-display text-xl text-paper">Добавить подключение</h2>
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
                  <span className="preset-title">{preset.title}</span>
                  <span className={`${TRUST_CLASS[preset.trust]} shrink-0`}>
                    {TRUST_SHORT[preset.trust]}
                  </span>
                </span>
                <span className="preset-pricing">{preset.pricing}</span>
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

function ConnectionList({ connections }: { connections: ProviderConnection[] }) {
  if (connections.length === 0) {
    return (
      <p className="text-paper-dim">
        Подключений нет — ревью и разговоры идут на локальной модели.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {connections.map((connection) => (
        <ConnectionCard key={connection.id} connection={connection} />
      ))}
    </ul>
  );
}

function ConnectionCard({ connection }: { connection: ProviderConnection }) {
  const queryClient = useQueryClient();
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
          <span className={TRUST_CLASS[connection.trust]}>{TRUST_LABEL[connection.trust]}</span>
          <ConnectionStatus connection={connection} />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="fact-chip">
            {connection.models.length === 1
              ? "одна модель"
              : `${connection.models.length} моделей`}
          </span>
          <span className="fact-chip">по умолчанию {connection.default_model}</span>
          <span className="fact-chip">{connection.has_api_key ? "ключ задан" : "без ключа"}</span>
          {connection.context_window ? (
            <span className="fact-chip">окно {connection.context_window.toLocaleString("ru")}</span>
          ) : null}
          {connection.catalogue_refreshed_at ? (
            <span className="fact-chip">
              перечень от {formatDateTime(connection.catalogue_refreshed_at)}
            </span>
          ) : null}
        </div>

        {connection.note ? (
          <p className="max-w-3xl text-[13px] leading-relaxed text-paper-dim">{connection.note}</p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button type="button" onClick={() => setIsOpen(!isOpen)} className="card-action">
            {isOpen ? "скрыть модели" : `показать модели (${connection.models.length})`}
          </button>
          <button
            type="button"
            disabled={reload.isPending}
            onClick={() => reload.mutate()}
            className="card-action card-action-primary"
          >
            {reload.isPending ? "спрашиваю провайдера…" : "обновить перечень"}
          </button>
          <button type="button" onClick={() => toggle.mutate()} className="card-action">
            {connection.is_enabled ? "выключить" : "включить"}
          </button>
          <button
            type="button"
            onClick={() => remove.mutate()}
            className="card-action card-action-danger ml-auto"
          >
            убрать
          </button>
        </div>

        {reload.error ? <p className="text-critical">{describe(reload.error)}</p> : null}
      </div>

      {isOpen ? (
        <div className="border-t border-tweed-dim px-5 py-4">
          <p className="case-label mb-3">
            так они выглядят в выборе при запуске ревью и разговора
          </p>
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
                  <span className="case-label shrink-0">по умолчанию</span>
                ) : (
                  <button
                    type="button"
                    disabled={choose.isPending}
                    onClick={() => choose.mutate(model)}
                    className="case-label shrink-0 text-paper-dim/60 hover:text-brass disabled:opacity-40"
                  >
                    выбрать
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
  if (!connection.is_enabled) {
    return (
      <span className="status-badge status-off">
        <span className="status-dot" aria-hidden />
        выключена
      </span>
    );
  }

  if (!connection.has_api_key && connection.base_url === "") {
    return (
      <span className="status-badge status-off">
        <span className="status-dot" aria-hidden />
        нужен ключ
      </span>
    );
  }

  return (
    <span className="status-badge status-live">
      <span className="status-dot" aria-hidden />
      подключена
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
        {preset.note}
        {preset.signup_url ? (
          <>
            {" "}
            <a
              href={preset.signup_url}
              target="_blank"
              rel="noreferrer"
              className="text-brass underline-offset-2 hover:underline"
            >
              получить ключ
            </a>
          </>
        ) : null}
      </p>

      <Field label="ключ — сохраняется зашифрованным и обратно не показывается">
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder="вставьте ключ провайдера"
          spellCheck={false}
          autoFocus
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
        />
      </Field>

      {offered.length > 0 ? (
        <Field label={`модель по умолчанию — провайдер предложил ${offered.length}`}>
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
          {probe.isPending ? "спрашиваю провайдера…" : "проверить"}
        </button>
        <button
          type="button"
          disabled={add.isPending || !name.trim() || !model.trim()}
          onClick={() => add.mutate()}
          className="card-action card-action-primary"
        >
          {add.isPending ? "завожу…" : "подключить"}
        </button>
        <button type="button" onClick={onDone} className="card-action">
          отмена
        </button>
        <button
          type="button"
          onClick={() => setIsDetailed(!isDetailed)}
          className="card-action ml-auto"
        >
          {isDetailed ? "скрыть подробности" : "настроить вручную"}
        </button>
      </div>

      <ProbeVerdict result={probe.data} error={probe.error} />

      {isDetailed ? (
        <div className="space-y-4 border-t border-tweed-dim pt-4">
          <Field label="имя подключения — им называется модель в списке выбора">
            <TextInput value={name} onChange={setName} placeholder="go" />
          </Field>
          <Field label="модель по умолчанию">
            <TextInput value={model} onChange={setModel} placeholder="kimi-k3" />
          </Field>
          <Field label="адрес сервера, если он нестандартный">
            <TextInput value={baseUrl} onChange={setBaseUrl} placeholder="https://…/v1" />
          </Field>
        </div>
      ) : null}

      {add.error ? <p className="text-critical">{describe(add.error)}</p> : null}
    </div>
  );
}

/** Ответ провайдера словами: работает ключ или нет и что он предлагает. */
function ProbeVerdict({ result, error }: { result?: ProbeResult; error: unknown }) {
  if (error) {
    return <p className="text-critical">{describe(error)}</p>;
  }
  if (!result) {
    return null;
  }
  if (!result.is_reachable) {
    return (
      <p className="border-l-2 border-critical bg-critical/5 px-3 py-2 text-[13px] text-paper">
        Провайдер не ответил: {result.detail}
      </p>
    );
  }
  return (
    <p className="border-l-2 border-confirmed bg-confirmed/5 px-3 py-2 text-[13px] text-paper">
      {result.detail}
      {result.models.length > 0
        ? " — все они появятся в списке выбора при запуске ревью и разговора"
        : ""}
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

function describe(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Сервис не отвечает.";
  }
  return error.message;
}
