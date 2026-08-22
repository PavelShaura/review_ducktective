import { lazy, Suspense } from "react";
import { Link, NavLink, Route, Routes } from "react-router";

const CaseListPage = lazy(() => import("@/pages/CaseListPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const CasePage = lazy(() => import("@/pages/CasePage"));
const MarksPage = lazy(() => import("@/pages/MarksPage"));
const NewCasePage = lazy(() => import("@/pages/NewCasePage"));

export function App() {
  return (
    <div className="relative z-10 min-h-screen">
      <Header />
      <main className="mx-auto w-full max-w-7xl px-5 pb-28">
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/" element={<CaseListPage />} />
            <Route path="/cases/new" element={<NewCasePage />} />
            <Route path="/cases/:runId" element={<CasePage />} />
            <Route path="/marks" element={<MarksPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

function Header() {
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
        <span className="flex items-baseline gap-3">
          <span className="font-display text-2xl font-semibold tracking-tight text-paper">
            review<span className="text-brass">_ducktective</span>
          </span>
          <span className="case-label hidden sm:inline">дела о качестве кода</span>
        </span>
      </Link>
      <nav className="flex items-center gap-4">
        <NavLink to="/chat" className="nav-action nav-chat" title="Спросить о коде">
          <span className="nav-live" aria-hidden />
          Чат
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
