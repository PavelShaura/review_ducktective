import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { useAuth } from "react-oidc-context";
import { Link, NavLink, Route, Routes } from "react-router";

import { api } from "@/api/client";
import type { CurrentUser, TenantRole } from "@/api/types";
import { provideAccessToken } from "@/api/token";
import { SignInGate } from "@/auth/SignInGate";

const CaseListPage = lazy(() => import("@/pages/CaseListPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CasePage = lazy(() => import("@/pages/CasePage"));
const MarksPage = lazy(() => import("@/pages/MarksPage"));
const NewCasePage = lazy(() => import("@/pages/NewCasePage"));
const OnboardingPage = lazy(() => import("@/pages/OnboardingPage"));
const ModelsPage = lazy(() => import("@/pages/ModelsPage"));
const OrganizationPage = lazy(() => import("@/pages/OrganizationPage"));

export function App() {
  return (
    <SignInGate>
      <Workspace />
    </SignInGate>
  );
}

/**
 * Рабочий стол вошедшего.
 *
 * Пока организации нет, показывается только её заведение: репозитории,
 * дела и разговоры принадлежат ей, и без неё им негде лежать.
 */
function Workspace() {
  const auth = useAuth();

  useEffect(() => {
    provideAccessToken(() => auth.user?.access_token);
  }, [auth.user]);

  const currentUser = useQuery({
    queryKey: ["current-user"],
    queryFn: api.getCurrentUser,
    enabled: Boolean(auth.user?.access_token),
  });

  return (
    <div className="relative z-10 min-h-screen">
      <Header user={currentUser.data} />
      <main className="mx-auto w-full max-w-7xl px-5 pb-28">
        <Suspense fallback={<Loading />}>
          {currentUser.isPending ? (
            <Loading />
          ) : currentUser.data?.organization ? (
            <Routes>
              <Route path="/" element={<CaseListPage />} />
              <Route path="/cases/new" element={<NewCasePage />} />
              <Route path="/cases/:runId" element={<CasePage />} />
              <Route path="/marks" element={<MarksPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/organization" element={<OrganizationPage />} />
              <Route path="/models" element={<ModelsPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          ) : (
            <OnboardingPage />
          )}
        </Suspense>
      </main>
    </div>
  );
}

const ROLE_LABEL: Record<TenantRole, string> = {
  owner: "владелец",
  member: "участник",
};

function Header({ user }: { user?: CurrentUser }) {
  const auth = useAuth();

  return (
    <header className="mx-auto mb-12 flex w-full max-w-7xl items-center justify-between px-5 pt-7">
      <Link to="/" className="group flex items-center gap-3">
        <img
          src="/mascot.webp"
          alt=""
          width={40}
          height={40}
          className="shrink-0 rounded-full"
        />
        <span className="brand">
          <span className="font-display text-2xl font-semibold tracking-tight text-paper">
            review<span className="text-brass">_ducktective</span>
          </span>
          <span className="brand-tagline hidden sm:block">дела о качестве кода</span>
        </span>
      </Link>
      <nav className="flex items-center gap-4">
        {user?.organization ? (
          <>
            <NavLink
              to="/organization"
              className="nav-org"
              title="Состав организации: участники, роли и приглашения"
            >
              <span className="nav-org-name">{user.organization.name}</span>
              <span className="nav-org-meta">
                состав · {user.member ? ROLE_LABEL[user.member.role] : "участник"}
              </span>
            </NavLink>
            <span className="nav-divider" aria-hidden />
          </>
        ) : null}
        <NavLink to="/chat" className="nav-action nav-chat" title="Спросить о коде">
          <span className="nav-live" aria-hidden />
          Чат
        </NavLink>

        <span className="nav-divider" aria-hidden />

        <NavLink to="/models" className="nav-action nav-models" title="Модели организации">
          модели
        </NavLink>

        <span className="nav-divider" aria-hidden />

        <NavLink to="/marks" className="nav-action nav-marks" title="Картотека вердиктов">
          <span className="nav-mark-stamp" aria-hidden>
            ✓
          </span>
          отметки
        </NavLink>

        <span className="nav-divider" aria-hidden />

        <NavLink to="/cases/new" className="nav-action nav-case" title="Запустить ревью диффа">
          + новое ревью
        </NavLink>

        <span className="nav-divider" aria-hidden />

        <button
          type="button"
          onClick={() => void auth.signoutRedirect()}
          className="nav-action nav-signout"
          title={user?.email ? `Выйти из учётной записи ${user.email}` : "Выйти"}
        >
          <span className="nav-signout-glyph" aria-hidden>
            →
          </span>
          выйти
        </button>
      </nav>
    </header>
  );
}

function Loading() {
  return <p className="case-label py-16 text-center">открываю папку…</p>;
}

function NotFound() {
  return (
    <div className="py-24 text-center">
      <p className="font-display text-3xl text-paper">Такого дела нет в архиве</p>
      <Link to="/" className="case-label mt-3 inline-block hover:text-brass">
        вернуться к списку
      </Link>
    </div>
  );
}
