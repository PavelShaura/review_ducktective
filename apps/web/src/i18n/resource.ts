import type { ru } from "@/i18n/ru";

/**
 * Форма словаря: те же ключи, что у русского, со строками в листьях.
 *
 * Тип снимается с русского словаря, а не пишется руками: единственный
 * источник ключей — сам текст, и добавить строку, забыв перевод, нельзя —
 * `tsc` откажет на английском словаре.
 */
export type Resource = DeepStrings<typeof ru>;

type DeepStrings<T> = {
  [K in keyof T]: T[K] extends string ? string : DeepStrings<T[K]>;
};
