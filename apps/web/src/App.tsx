import { lazy, Suspense } from "react";
import { Link, Route, Routes } from "react-router";

const CaseListPage = lazy(() => import("@/pages/CaseListPage"));
const CasePage = lazy(() => import("@/pages/CasePage"));
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
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

function Header() {
  return (
    <header className="mx-auto mb-12 flex w-full max-w-7xl items-baseline justify-between px-5 pt-7">
      <Link to="/" className="group flex items-baseline gap-3">
        <span className="font-display text-2xl font-semibold tracking-tight text-paper">
          review<span className="text-brass">_ducktective</span>
        </span>
        <span className="case-label hidden sm:inline">дела о качестве кода</span>
      </Link>
      <Link
        to="/cases/new"
        className="rounded-case border border-tweed px-4 py-2 font-mono text-[13px] tracking-wide text-paper-dim transition-colors hover:border-brass hover:text-brass"
      >
        новое дело
      </Link>
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
