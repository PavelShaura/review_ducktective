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
        <div className="flex flex-wrap gap-2">
          {presets.data.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => setChosen(preset)}
              className={`case-label rounded-case border px-3 py-2 hover:text-brass ${
                chosen?.key === preset.key
                  ? "border-brass text-brass"
                  : "border-tweed-dim text-paper-dim"
              }`}
            >
              {preset.title}
            </button>
          ))}
        </div>
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

  return (
    <li className="rounded-case border border-tweed-dim bg-ink-raised px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <span className="min-w-0 space-y-1">
          <span className="flex flex-wrap items-baseline gap-3">
            <span className="text-paper">{connection.name}</span>
            <span className="case-label">{TRUST_LABEL[connection.trust]}</span>
            {connection.is_enabled ? null : <span className="case-label">выключено</span>}
          </span>
          <span className="block text-[13px] text-paper-dim">
            {connection.models.length === 1
              ? connection.models[0]
              : `${connection.models.length} моделей · по умолчанию ${connection.default_model}`}
            {connection.has_api_key ? " · ключ задан" : " · без ключа"}
            {connection.context_window ? ` · окно ${connection.context_window}` : ""}
          </span>
          {connection.catalogue_refreshed_at ? (
            <span className="case-label block">
              перечень обновлён {formatDateTime(connection.catalogue_refreshed_at)}
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className="case-label text-paper-dim hover:text-brass"
          >
            {isOpen ? "скрыть модели" : "модели"}
          </button>
          <button
            type="button"
            disabled={reload.isPending}
            onClick={() => reload.mutate()}
            className="case-label text-paper-dim hover:text-brass disabled:opacity-40"
          >
            {reload.isPending ? "спрашиваю…" : "обновить перечень"}
          </button>
          <button
            type="button"
            onClick={() => toggle.mutate()}
            className="case-label text-paper-dim hover:text-brass"
          >
            {connection.is_enabled ? "выключить" : "включить"}
          </button>
          <button
            type="button"
            onClick={() => remove.mutate()}
            className="case-label text-paper-dim hover:text-critical"
          >
            убрать
          </button>
        </span>
      </div>

      {connection.note ? (
        <p className="mt-2 text-[13px] text-paper-dim">{connection.note}</p>
      ) : null}

      {isOpen ? (
        <ul className="mt-3 grid gap-1 border-t border-tweed-dim pt-3 sm:grid-cols-2">
          {connection.models.map((model) => (
            <li key={model} className="font-mono text-[13px] text-paper-dim">
              {connection.name}/{model}
            </li>
          ))}
        </ul>
      ) : null}

      {reload.error ? <p className="mt-2 text-critical">{describe(reload.error)}</p> : null}
    </li>
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
          className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper-dim hover:text-brass disabled:opacity-40"
        >
          {probe.isPending ? "спрашиваю провайдера…" : "проверить"}
        </button>
        <button
          type="button"
          disabled={add.isPending || !name.trim() || !model.trim()}
          onClick={() => add.mutate()}
          className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
        >
          {add.isPending ? "завожу…" : "подключить"}
        </button>
        <button type="button" onClick={onDone} className="case-label text-paper-dim hover:text-brass">
          отмена
        </button>
        <button
          type="button"
          onClick={() => setIsDetailed(!isDetailed)}
          className="case-label ml-auto text-paper-dim hover:text-brass"
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
