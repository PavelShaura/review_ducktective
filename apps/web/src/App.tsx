import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "react-oidc-context";
import { Link, NavLink, Route, Routes } from "react-router";

import { api } from "@/api/client";
import { provideAccessToken } from "@/api/token";
import type { CurrentUser } from "@/api/types";
import { SignInGate } from "@/auth/SignInGate";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { SectionIcon } from "@/components/SectionIcon";
import type { SectionKey } from "@/components/SectionIcon";

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
 * индекс и модели, — и в конце накопленные отметки.
 *
 * Слева только разделы, справа только действия. Организация — не раздел
 * и не действие, а подпись на папке: чьё это дело. Она стоит под названием
 * приложения, на месте слогана, и ведёт на страницу состава; слоган
 * остаётся тому, у кого организации ещё нет.
 *
 * Журнала здесь нет: он виден не всем и добавляется после общих разделов.
 * На ширине `xl` у него один значок — подпись не помещается вместе с остальными.
 */
const SECTIONS: { to: string; key: Exclude<SectionKey, "logs"> }[] = [
  { to: "/", key: "cases" },
  { to: "/chat", key: "chat" },
  { to: "/indexes", key: "indexes" },
  { to: "/models", key: "models" },
  { to: "/marks", key: "marks" },
];

function Header({ user }: { user?: CurrentUser }) {
  const auth = useAuth();
  const isLifted = useLifted();
  const { t } = useTranslation();

  return (
    <header className={`topbar sticky top-0 z-20 backdrop-blur ${isLifted ? "topbar-lifted" : ""}`}>
      <div className="menu-scroll mx-auto flex w-full max-w-7xl flex-nowrap items-center gap-3 overflow-x-auto px-5 py-3">
        <span className="flex shrink-0 items-center gap-3">
          <Link to="/" className="brand-link shrink-0">
            <img
              src="/mascot.webp"
              alt=""
              width={36}
              height={36}
              className="brand-mascot rounded-full"
            />
          </Link>
          <span className="brand">
            <Link
              to="/"
              className="brand-link font-display text-xl font-semibold tracking-tight text-paper"
            >
              review<span className="text-brass">_ducktective</span>
            </Link>
            {user?.organization ? (
              <NavLink
                to="/organization"
                className="brand-org hidden sm:block"
                title={t("app.nav.organizationTitle")}
              >
                <span className="brand-org-name">{user.organization.name}</span>
                <span className="brand-org-meta">
                  {" · "}
                  {user.member
                    ? t(`organization.role.${user.member.role}`)
                    : t("app.nav.organization")}
                </span>
              </NavLink>
            ) : (
              <span className="brand-tagline hidden sm:block">{t("app.tagline")}</span>
            )}
          </span>
        </span>

        <nav className="menu-tray flex shrink-0 items-center gap-0.5">
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              end={section.to === "/"}
              title={t(`app.nav.${section.key}Title`)}
              className="menu-link"
            >
              <SectionIcon section={section.key} />
              {t(`app.nav.${section.key}`)}
            </NavLink>
          ))}

          {user?.is_installation_admin ? (
            <NavLink
              to="/logs"
              className="menu-link"
              title={t("app.nav.logsTitle")}
              aria-label={t("app.nav.logs")}
            >
              <SectionIcon section="logs" />
              <span className="hidden 2xl:inline">{t("app.nav.logs")}</span>
            </NavLink>
          ) : null}
        </nav>

        <span className="ml-auto flex min-w-0 items-center gap-3">
          <NavLink to="/cases/new" className="menu-action shrink-0" title={t("app.newReviewTitle")}>
            {t("app.newReview")}
          </NavLink>

          <LanguageSwitch />

          <button
            type="button"
            onClick={() => void auth.signoutRedirect()}
            className="menu-signout shrink-0"
            aria-label={t("app.signOut")}
            title={
              user?.email
                ? t("app.signOutTitle", { email: user.email })
                : t("app.signOutTitleShort")
            }
          >
            <span className="menu-signout-glyph" aria-hidden>
              →
            </span>
            <span className="hidden 2xl:inline">{t("app.signOut")}</span>
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
  const { t } = useTranslation();
  return <p className="case-label py-16 text-center">{t("app.loading")}</p>;
}

function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="py-24 text-center">
      <p className="font-display text-3xl text-paper">{t("app.notFoundTitle")}</p>
      <Link to="/" className="case-label mt-3 inline-block hover:text-brass">
        {t("app.notFoundBack")}
      </Link>
    </div>
  );
}
