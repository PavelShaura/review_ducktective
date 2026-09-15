import { useTranslation } from "react-i18next";

import { LANGUAGES, currentLanguage } from "@/i18n";
import type { Language } from "@/i18n";

/**
 * Переключатель языка — две буквы, как штамп на папке.
 *
 * Стоит в шапке и виден всегда: язык меняют не в настройках, а в тот
 * момент, когда текст перед глазами оказался не тем.
 */
export function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  const active = currentLanguage();

  return (
    <span
      role="group"
      aria-label={t("language.title")}
      className="language-switch shrink-0"
      title={t("language.title")}
    >
      {LANGUAGES.map((language: Language) => (
        <button
          key={language}
          type="button"
          onClick={() => void i18n.changeLanguage(language)}
          aria-pressed={language === active}
          className="language-option"
        >
          {t(`language.${language}`)}
        </button>
      ))}
    </span>
  );
}
