import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link, NavLink, Route, Routes } from "react-router";

import { api } from "@/api/client";
import { provideAccessToken } from "@/api/token";
import type { CurrentUser, TenantRole } from "@/api/types";
import { SignInGate } from "@/auth/SignInGate";

const CaseListPage = lazy(() => import("@/pages/CaseListPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CasePage = lazy(() => import("@/pages/CasePage"));
const IndexesPage = lazy(() => import("@/pages/IndexesPage"));
const MarksPage = lazy(() => import("@/pages/MarksPage"));
const ModelsPage = lazy(() => import("@/pages/ModelsPage"));
const NewCasePage = lazy(() => import("@/pages/NewCasePage"));
const OnboardingPage = lazy(() => import("@/pages/OnboardingPage"));
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
      <main className="mx-auto w-full max-w-7xl px-5 pb-28 pt-8">
        <Suspense fallback={<Loading />}>
          {currentUser.isPending ? (
            <Loading />
          ) : currentUser.data?.organization ? (
            <Routes>
              <Route path="/" element={<CaseListPage />} />
              <Route path="/cases/new" element={<NewCasePage />} />
              <Route path="/cases/:runId" element={<CasePage />} />
              <Route path="/indexes" element={<IndexesPage />} />
              <Route path="/marks" element={<MarksPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/models" element={<ModelsPage />} />
              <Route path="/organization" element={<OrganizationPage />} />
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

/**
 * Разделы по порядку работы: сначала дела, потом то, на чём они держатся —
 * индекс и модели, — и в конце накопленные отметки.
 *
 * Разговор помечен живым огоньком: это единственный раздел, где что-то
 * происходит в реальном времени.
 */
const SECTIONS: {
  to: string;
  label: string;
  title: string;
  glyph?: string;
  isLive?: boolean;
}[] = [
  { to: "/", label: "список ревью", title: "Все прогоны ревью", glyph: "§" },
  { to: "/chat", label: "чат", title: "Спросить о коде своими словами", isLive: true },
  { to: "/indexes", label: "индексы", title: "Что разобрано, когда и чем собрать заново", glyph: "≡" },
  { to: "/models", label: "модели", title: "Подключения к провайдерам моделей", glyph: "◈" },
  { to: "/marks", label: "отметки", title: "Картотека вердиктов по находкам", glyph: "✓" },
];

function Header({ user }: { user?: CurrentUser }) {
  const auth = useAuth();
  const isLifted = useLifted();

  return (
    <header className={`topbar sticky top-0 z-20 backdrop-blur ${isLifted ? "topbar-lifted" : ""}`}>
      <div className="mx-auto flex w-full max-w-7xl flex-nowrap items-center gap-3 px-5 py-3">
        <Link to="/" className="brand-link flex shrink-0 items-center gap-3">
          <img
            src="/mascot.webp"
            alt=""
            width={36}
            height={36}
            className="brand-mascot rounded-full"
          />
          <span className="brand">
            <span className="font-display text-xl font-semibold tracking-tight text-paper">
              review<span className="text-brass">_ducktective</span>
            </span>
            <span className="brand-tagline hidden sm:block">дела о качестве кода</span>
          </span>
        </Link>

        <span className="menu-divider hidden lg:block" aria-hidden />

        <nav className="menu-scroll flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              end={section.to === "/"}
              title={section.title}
              className="menu-link"
            >
              {section.isLive ? (
                <span className="menu-live" aria-hidden />
              ) : (
                <span className="menu-glyph" aria-hidden>
                  {section.glyph}
                </span>
              )}
              {section.label}
            </NavLink>
          ))}
        </nav>

        <span className="flex shrink-0 items-center gap-3">
          <NavLink to="/cases/new" className="menu-action" title="Запустить ревью диффа">
            + новое ревью
          </NavLink>

          <span className="menu-divider hidden xl:block" aria-hidden />

          {user?.organization ? (
            <NavLink
              to="/organization"
              className="nav-org hidden xl:inline-flex"
              title="Состав организации: участники, роли и приглашения"
            >
              <span className="nav-org-name">{user.organization.name}</span>
              <span className="nav-org-meta">
                состав · {user.member ? ROLE_LABEL[user.member.role] : "участник"}
              </span>
            </NavLink>
          ) : null}

          <button
            type="button"
            onClick={() => void auth.signoutRedirect()}
            className="menu-signout"
            title={user?.email ? `Выйти из учётной записи ${user.email}` : "Выйти"}
          >
            <span className="menu-signout-glyph" aria-hidden>
              →
            </span>
            выйти
          </button>
        </span>
      </div>
    </header>
  );
}

/**
 * Уехала ли страница под шапку.
 *
 * Тень отделяет шапку от содержимого только тогда, когда под неё что-то
 * прокрутили: над нетронутой страницей она обещала бы прокрутку, которой
 * ещё нет.
 */
function useLifted(): boolean {
  const [isLifted, setIsLifted] = useState(() => window.scrollY > 4);

  useEffect(() => {
    const onScroll = () => setIsLifted(window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return isLifted;
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
