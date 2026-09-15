import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link, NavLink, Route, Routes } from "react-router";

import { api } from "@/api/client";
import { provideAccessToken } from "@/api/token";
import type { CurrentUser } from "@/api/types";
import { SignInGate } from "@/auth/SignInGate";

const CaseListPage = lazy(() => import("@/pages/CaseListPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CasePage = lazy(() => import("@/pages/CasePage"));
const IndexesPage = lazy(() => import("@/pages/IndexesPage"));
const LogsPage = lazy(() => import("@/pages/LogsPage"));
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
 * дела и разговоры принадлежат ей, и без неё им негде лежать. Исключение —
 * журнал установки: он принадлежит установке, и администратор открывает
 * его, даже не состоя ни в одной организации.
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
              {currentUser.data.is_installation_admin ? (
                <Route path="/logs" element={<LogsPage />} />
              ) : null}
              <Route path="*" element={<NotFound />} />
            </Routes>
          ) : currentUser.data?.is_installation_admin ? (
            <Routes>
              <Route path="/logs" element={<LogsPage />} />
              <Route path="*" element={<OnboardingPage />} />
            </Routes>
          ) : (
            <OnboardingPage />
          )}
        </Suspense>
      </main>
    </div>
  );
}

/**
 * Разделы по порядку работы: сначала дела, потом то, на чём они держатся —
 * индекс и модели, — затем накопленные отметки и в конце — кто всем этим
 * занимается.
 *
 * Разговор помечен живым огоньком: это единственный раздел, где что-то
 * происходит в реальном времени.
 *
 * Слева только разделы, справа только действия: пока имя организации стояло
 * справа карточкой, она единственная умела сжиматься и первой теряла текст
 * при каждом новом пункте. Имя и роль показывает сама страница состава.
 *
 * Журнала здесь нет: он виден не всем и добавляется после общих разделов.
 * На ширине `xl` у него один глиф — подпись не помещается вместе с остальными.
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
  {
    to: "/organization",
    label: "состав",
    title: "Состав организации: участники, роли и приглашения",
    glyph: "⌂",
  },
];

function Header({ user }: { user?: CurrentUser }) {
  const auth = useAuth();
  const isLifted = useLifted();

  return (
    <header className={`topbar sticky top-0 z-20 backdrop-blur ${isLifted ? "topbar-lifted" : ""}`}>
      <div className="menu-scroll mx-auto flex w-full max-w-7xl flex-nowrap items-center gap-3 overflow-x-auto px-5 py-3">
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

        <nav className="flex shrink-0 items-center gap-1">
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

          {user?.is_installation_admin ? (
            <NavLink
              to="/logs"
              className="menu-link"
              title="Журнал установки: api и воркеры, только для администратора"
              aria-label="журнал"
            >
              <span className="menu-glyph" aria-hidden>
                ¶
              </span>
              <span className="hidden 2xl:inline">журнал</span>
            </NavLink>
          ) : null}
        </nav>

        <span className="ml-auto flex min-w-0 items-center gap-3">
          <NavLink to="/cases/new" className="menu-action shrink-0" title="Запустить ревью диффа">
            + новое ревью
          </NavLink>

          <button
            type="button"
            onClick={() => void auth.signoutRedirect()}
            className="menu-signout shrink-0"
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
