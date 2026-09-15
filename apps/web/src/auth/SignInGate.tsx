import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";

import { LanguageSwitch } from "@/components/LanguageSwitch";

/**
 * Порог входа: до подтверждения личности дальше не пускает.
 *
 * Раньше организация приходила параметром запроса, и подставленный
 * идентификатор открывал чужие дела вместе с содержимым кода. Теперь
 * её называет токен, а значит без входа показывать нечего.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { t } = useTranslation();

  if (auth.isLoading) {
    return <Notice>{t("signIn.checking")}</Notice>;
  }

  if (auth.error) {
    return (
      <div className="py-24 text-center">
        <div className="mb-8 flex justify-center">
          <LanguageSwitch />
        </div>
        <p className="font-display text-2xl text-paper">{t("signIn.providerDown")}</p>
        <p className="mt-3 text-paper-dim">{auth.error.message}</p>
        <SignInButton label={t("signIn.retry")} />
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="py-24 text-center">
        <div className="mb-8 flex justify-center">
          <LanguageSwitch />
        </div>
        <p className="font-display text-3xl text-paper">{t("signIn.title")}</p>
        <p className="mx-auto mt-3 max-w-lg text-paper-dim">{t("signIn.body")}</p>
        <SignInButton label={t("signIn.signIn")} />
      </div>
    );
  }

  return <>{children}</>;
}

function SignInButton({ label }: { label: string }) {
  const auth = useAuth();
  return (
    <button
      type="button"
      onClick={() => void auth.signinRedirect()}
      className="case-label mt-6 rounded-case border border-tweed-dim bg-ink-raised px-5 py-2 text-paper hover:text-brass"
    >
      {label}
    </button>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return <p className="case-label py-24 text-center">{children}</p>;
}
