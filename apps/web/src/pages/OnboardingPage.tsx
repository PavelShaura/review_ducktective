import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/api/client";

/**
 * Первый экран вошедшего, у которого ещё нет организации.
 *
 * Состояние обычное, а не ошибочное: человек только что зарегистрировался
 * либо получил ссылку-приглашение. Оба пути открыты сразу — угадывать,
 * какой из них его, незачем.
 */
export default function OnboardingPage() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["current-user"] });

  return (
    <div className="mx-auto max-w-2xl space-y-12 py-10">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">Заведите папку дела</h1>
        <p className="mt-3 text-paper-dim">
          Репозитории, индексы и находки принадлежат организации. Создайте свою
          или примите приглашение в чужую.
        </p>
      </header>

      <CreateOrganization onDone={refresh} />
      <AcceptInvitation onDone={refresh} />
    </div>
  );
}

function CreateOrganization({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () => api.createOrganization(slug.trim(), name.trim()),
    onSuccess: onDone,
  });

  return (
    <section className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-6">
      <h2 className="font-display text-xl text-paper">Своя организация</h2>
      <Field label="название">
        <TextInput value={name} onChange={setName} placeholder="Отдел разработки" />
      </Field>
      <Field label="короткое имя">
        <TextInput value={slug} onChange={setSlug} placeholder="dev-team" />
      </Field>
      <button
        type="button"
        disabled={create.isPending || !name.trim() || slug.trim().length < 3}
        onClick={() => create.mutate()}
        className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
      >
        {create.isPending ? "завожу…" : "создать"}
      </button>
      <Failure error={create.error} />
    </section>
  );
}

function AcceptInvitation({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");

  const accept = useMutation({
    mutationFn: () => api.acceptInvitation(token.trim()),
    onSuccess: onDone,
  });

  return (
    <section className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-6">
      <h2 className="font-display text-xl text-paper">Приглашение</h2>
      <p className="text-paper-dim">
        Ссылка выписывается на ваш почтовый адрес и действует неделю.
      </p>
      <Field label="код приглашения">
        <TextInput value={token} onChange={setToken} placeholder="вставьте код из ссылки" />
      </Field>
      <button
        type="button"
        disabled={accept.isPending || !token.trim()}
        onClick={() => accept.mutate()}
        className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
      >
        {accept.isPending ? "проверяю…" : "принять"}
      </button>
      <Failure error={accept.error} />
    </section>
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

function Failure({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  return <p className="text-critical">{describe(error)}</p>;
}

function describe(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "Сервис не отвечает.";
  }
  if (error.status === 404) {
    return "Приглашение не найдено или больше не действует.";
  }
  if (error.status === 403) {
    return "Приглашение выписано на другой почтовый адрес.";
  }
  return error.message;
}
