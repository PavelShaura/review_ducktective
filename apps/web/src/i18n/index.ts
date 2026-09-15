import i18next from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import { en } from "@/i18n/en";
import { ru } from "@/i18n/ru";

export const LANGUAGES = ["ru", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

/** Локаль для дат и чисел: язык интерфейса задаёт и формат. */
export const LOCALE: Record<Language, string> = {
  ru: "ru-RU",
  en: "en-GB",
};

const STORAGE_KEY = "ducktective.language";

/**
 * Язык интерфейса.
 *
 * Выбор запоминается в браузере и переживает перезагрузку; до первого
 * выбора берётся язык браузера, а если он не из списка — русский, на
 * котором интерфейс написан изначально.
 *
 * Строки лежат в сборке, а не грузятся по сети: их два языка и один
 * файл на каждый, и переключение обязано быть мгновенным.
 */
void i18next
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      ru: { translation: ru },
      en: { translation: en },
    },
    fallbackLng: "ru",
    supportedLngs: [...LANGUAGES],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: STORAGE_KEY,
      caches: ["localStorage"],
    },
  });

i18next.on("languageChanged", (language) => {
  document.documentElement.lang = language;
});

export function currentLanguage(): Language {
  const base = i18next.resolvedLanguage ?? i18next.language;
  return LANGUAGES.find((candidate) => candidate === base) ?? "ru";
}

export function currentLocale(): string {
  return LOCALE[currentLanguage()];
}

export { i18next };
