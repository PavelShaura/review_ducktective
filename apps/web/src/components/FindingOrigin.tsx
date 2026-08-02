import type { FindingCategory } from "@/api/types";

const CATEGORY_LABEL: Record<FindingCategory, string> = {
  correctness: "корректность",
  security: "безопасность",
  performance: "производительность",
  style: "стиль",
  tests: "тесты",
  architecture: "архитектура",
};

const REVIEWER_LABEL: Record<string, string> = {
  correctness: "корректность",
  security: "безопасность",
  performance: "производительность",
  conventions: "соглашения",
};

/** Прогоны, снятые до появления специализаций, несут прежние имена. */
function reviewerLabel(producerName: string): string {
  const kind = producerName.replace(/^reviewer:/, "");
  return REVIEWER_LABEL[kind] ?? kind;
}

interface Props {
  category: FindingCategory;
  producerName: string;
}

/**
 * Тип замечания и, если он не совпадает с фокусом нашедшего, сам ревьюер.
 *
 * Обычно они совпадают, и повторять одно слово дважды незачем. Но ревьюер
 * безопасности вправе выставить категорию `correctness`, и вот тогда знать,
 * чьими глазами это увидено, важно: вес замечания зависит от того, кто его
 * вынес.
 */
export function FindingOrigin({ category, producerName }: Props) {
  const type = CATEGORY_LABEL[category] ?? category;
  const reviewer = reviewerLabel(producerName);

  return (
    <>
      тип: {type}
      {reviewer === type ? null : (
        <>
          <span className="mx-2 opacity-40">·</span>
          ревьюер: {reviewer}
        </>
      )}
    </>
  );
}
