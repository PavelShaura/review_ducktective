import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

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
  const { t } = useTranslation();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["current-user"] });

  return (
    <div className="mx-auto max-w-2xl space-y-12 py-10">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">{t("onboarding.title")}</h1>
        <p className="mt-3 text-paper-dim">{t("onboarding.intro")}</p>
      </header>

      <CreateOrganization onDone={refresh} />
      <AcceptInvitation onDone={refresh} />
    </div>
  );
}

function CreateOrganization({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () => api.createOrganization(slug.trim(), name.trim()),
    onSuccess: onDone,
  });

  return (
    <section className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-6">
      <h2 className="font-display text-xl text-paper">{t("onboarding.ownTitle")}</h2>
      <Field label={t("onboarding.name")}>
        <TextInput value={name} onChange={setName} placeholder={t("onboarding.namePlaceholder")} />
      </Field>
      <Field label={t("onboarding.slug")}>
        <TextInput value={slug} onChange={setSlug} placeholder="dev-team" />
      </Field>
      <button
        type="button"
        disabled={create.isPending || !name.trim() || slug.trim().length < 3}
        onClick={() => create.mutate()}
        className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
      >
        {create.isPending ? t("onboarding.creating") : t("onboarding.create")}
      </button>
      <Failure error={create.error} />
    </section>
  );
}

function AcceptInvitation({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [token, setToken] = useState("");

  const accept = useMutation({
    mutationFn: () => api.acceptInvitation(token.trim()),
    onSuccess: onDone,
  });

  return (
    <section className="space-y-4 rounded-case border border-tweed-dim bg-ink-raised p-6">
      <h2 className="font-display text-xl text-paper">{t("onboarding.invitationTitle")}</h2>
      <p className="text-paper-dim">{t("onboarding.invitationBody")}</p>
      <Field label={t("onboarding.code")}>
        <TextInput
          value={token}
          onChange={setToken}
          placeholder={t("onboarding.codePlaceholder")}
        />
      </Field>
      <button
        type="button"
        disabled={accept.isPending || !token.trim()}
        onClick={() => accept.mutate()}
        className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
      >
        {accept.isPending ? t("onboarding.checking") : t("onboarding.accept")}
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
  const { t } = useTranslation();
  if (!error) {
    return null;
  }

  return <p className="text-critical">{describe(t, error)}</p>;
}

function describe(t: TFunction, error: unknown): string {
  if (!(error instanceof ApiError)) {
    return t("common.serviceDown");
  }
  if (error.status === 404) {
    return t("onboarding.notFound");
  }
  if (error.status === 403) {
    return t("onboarding.wrongEmail");
  }
  return error.message;
}
