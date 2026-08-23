import { useAuth } from "react-oidc-context";
import type { ReactNode } from "react";

/**
 * Порог входа: до подтверждения личности дальше не пускает.
 *
 * Раньше организация приходила параметром запроса, и подставленный
 * идентификатор открывал чужие дела вместе с содержимым кода. Теперь
 * её называет токен, а значит без входа показывать нечего.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.isLoading) {
    return <Notice>проверяю пропуск…</Notice>;
  }

  if (auth.error) {
    return (
      <div className="py-24 text-center">
        <p className="font-display text-2xl text-paper">Провайдер личности не отвечает</p>
        <p className="mt-3 text-paper-dim">{auth.error.message}</p>
        <SignInButton label="попробовать снова" />
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="py-24 text-center">
        <p className="font-display text-3xl text-paper">Дела выдаются по пропуску</p>
        <p className="mx-auto mt-3 max-w-lg text-paper-dim">
          Вход подтверждается провайдером личности. Пароль остаётся у него —
          приложение его не видит и не хранит.
        </p>
        <SignInButton label="войти" />
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
