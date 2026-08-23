import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/api/client";
import type { ModelPreset, ModelProfile, ModelTrust } from "@/api/types";

const TRUST_LABEL: Record<ModelTrust, string> = {
  local: "локальная",
  private_remote: "не учится на запросах",
  training_remote: "учится на запросах",
};

/**
 * Модели организации: что заведено и что можно завести.
 *
 * Экран нужен ровно потому, что бесплатные тиры перебирают — этот кончился,
 * тот не умеет инструменты, третий отвечает быстрее. Правка файла с
 * перезапуском сервиса делает перебор занятием на вечер, и им не занимаются.
 */
export default function ModelsPage() {
  const profiles = useQuery({ queryKey: ["model-profiles"], queryFn: api.listModelProfiles });
  const presets = useQuery({ queryKey: ["model-presets"], queryFn: api.listModelPresets });
  const [chosen, setChosen] = useState<ModelPreset | null>(null);

  if (profiles.isPending || presets.isPending) {
    return <p className="case-label py-16 text-center">достаю картотеку моделей…</p>;
  }

  if (profiles.isError || presets.isError) {
    return <p className="py-20 text-center text-paper-dim">Сервис не отвечает.</p>;
  }

  return (
    <div className="space-y-12">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">Модели</h1>
        <p className="mt-3 max-w-3xl text-paper-dim">
          Локальная модель настроена на сервере и доступна всегда. Удалённые заводит
          организация: ключ хранится зашифрованным и обратно не показывается.
          Куда именно разрешено уезжать коду, решает политика репозитория.
        </p>
      </header>

      <ProfileList profiles={profiles.data} />

      <section className="space-y-4">
        <h2 className="font-display text-xl text-paper">Добавить</h2>
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
        {chosen ? <AddModelForm preset={chosen} onDone={() => setChosen(null)} /> : null}
      </section>
    </div>
  );
}

function ProfileList({ profiles }: { profiles: ModelProfile[] }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["model-profiles"] });

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateModelProfile(id, { is_enabled: enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteModelProfile(id),
    onSuccess: refresh,
  });

  if (profiles.length === 0) {
    return (
      <p className="text-paper-dim">
        Удалённых моделей нет — ревью и разговоры идут на локальной.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-tweed-dim rounded-case border border-tweed-dim bg-ink-raised">
      {profiles.map((profile) => (
        <li key={profile.id} className="flex items-start justify-between gap-4 px-5 py-4">
          <span className="min-w-0 space-y-1">
            <span className="flex items-baseline gap-3">
              <span className="text-paper">{profile.name}</span>
              <span className="case-label">{TRUST_LABEL[profile.trust]}</span>
              {profile.is_enabled ? null : <span className="case-label">выключена</span>}
            </span>
            <span className="block truncate font-mono text-[13px] text-paper-dim">
              {profile.model}
              {profile.base_url ? ` · ${profile.base_url}` : ""}
            </span>
            <span className="block text-[13px] text-paper-dim">
              {profile.has_api_key ? "ключ задан" : "без ключа"}
              {profile.context_window ? ` · окно ${profile.context_window}` : ""}
              {profile.supports_tools ? " · умеет инструменты" : " · без инструментов"}
            </span>
            {profile.note ? (
              <span className="block text-[13px] text-paper-dim">{profile.note}</span>
            ) : null}
          </span>
          <span className="flex shrink-0 items-center gap-3">
            <button
              type="button"
              onClick={() => toggle.mutate({ id: profile.id, enabled: !profile.is_enabled })}
              className="case-label text-paper-dim hover:text-brass"
            >
              {profile.is_enabled ? "выключить" : "включить"}
            </button>
            <button
              type="button"
              onClick={() => remove.mutate(profile.id)}
              className="case-label text-paper-dim hover:text-critical"
            >
              убрать
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}

function AddModelForm({ preset, onDone }: { preset: ModelPreset; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(preset.key);
  const [model, setModel] = useState(preset.model);
  const [baseUrl, setBaseUrl] = useState(preset.base_url);
  const [apiKey, setApiKey] = useState("");

  const add = useMutation({
    mutationFn: () =>
      api.addModelProfile({
        name: name.trim(),
        model: model.trim(),
        api_key: apiKey.trim(),
        provider: preset.provider,
        base_url: baseUrl.trim(),
        trust: preset.trust,
        supports_tools: preset.supports_tools,
        context_window: preset.context_window,
        note: preset.note,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["model-profiles"] });
      onDone();
    },
  });

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

      <Field label="имя в списке выбора">
        <TextInput value={name} onChange={setName} placeholder="free" />
      </Field>
      <Field label="идентификатор модели у провайдера">
        <TextInput value={model} onChange={setModel} placeholder="openrouter/model:free" />
      </Field>
      <Field label="адрес сервера, если нужен">
        <TextInput value={baseUrl} onChange={setBaseUrl} placeholder="https://…/v1" />
      </Field>
      <Field label="ключ — сохраняется зашифрованным и обратно не показывается">
        <input
          type="password"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          placeholder="sk-…"
          spellCheck={false}
          className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
        />
      </Field>

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={add.isPending || !name.trim() || !model.trim()}
          onClick={() => add.mutate()}
          className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
        >
          {add.isPending ? "завожу…" : "завести"}
        </button>
        <button type="button" onClick={onDone} className="case-label text-paper-dim hover:text-brass">
          отмена
        </button>
      </div>

      {add.error ? <p className="text-critical">{describe(add.error)}</p> : null}
    </div>
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
