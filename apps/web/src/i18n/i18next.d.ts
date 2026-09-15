import type { ru } from "@/i18n/ru";

/**
 * Ключи `t()` проверяются на типах: `t("case.lable")` не собирается.
 * Формы числа (`_one`, `_few`, …) i18next снимает с ключа сам.
 */
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: {
      translation: typeof ru;
    };
  }
}
