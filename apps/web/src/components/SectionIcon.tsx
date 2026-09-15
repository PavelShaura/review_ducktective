export type SectionKey = "cases" | "chat" | "indexes" | "models" | "marks" | "logs";

/**
 * Значки разделов — по одному на раздел, каждый своего цвета.
 *
 * Рисуются здесь, а не грузятся файлами: шесть контуров по паре штрихов
 * не стоят запроса к серверу, а цвет и толщина линии должны совпадать
 * с текстом рядом, то есть жить в тех же токенах темы.
 *
 * Цвет — метка раздела, а не состояние: в ряду из шести пунктов взгляд
 * находит нужный по цвету быстрее, чем читает подпись. Ни один не
 * анимирован: один живой огонёк среди пяти неподвижных значков читался
 * как сбой, а не как подсказка.
 */
const PATHS: Record<SectionKey, string> = {
  /* Папка дела с закладкой */
  cases: "M2 4.5A1.5 1.5 0 0 1 3.5 3H6l1.5 1.5H12.5A1.5 1.5 0 0 1 14 6v6.5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5V4.5Z M2 7.5h12",
  /* Реплика разговора */
  chat: "M3 3.5h10a1 1 0 0 1 1 1V10a1 1 0 0 1-1 1H7l-3.5 2.5V11H3a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z M5.5 7h5",
  /* Слои индекса */
  indexes: "M8 2.5 14 5.5 8 8.5 2 5.5 8 2.5Z M2 8.5l6 3 6-3 M2 11.5l6 3 6-3",
  /* Кристалл модели с выводами */
  models: "M5 5h6v6H5V5Z M7 2v3 M9 2v3 M7 11v3 M9 11v3 M2 7h3 M2 9h3 M11 7h3 M11 9h3",
  /* Штамп вердикта */
  marks: "M8 2.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11Z M5.5 8l1.8 1.8L10.8 6",
  /* Строки журнала */
  logs: "M3 3.5h10 M3 6.5h7 M3 9.5h10 M3 12.5h5",
};

interface Props {
  section: SectionKey;
}

export function SectionIcon({ section }: Props) {
  return (
    <svg
      className={`section-icon section-icon-${section}`}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={PATHS[section]} />
    </svg>
  );
}
