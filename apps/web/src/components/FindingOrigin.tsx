import { useTranslation } from "react-i18next";

import type { FindingCategory } from "@/api/types";

const KNOWN_KINDS = new Set([
  "correctness",
  "security",
  "performance",
  "style",
  "tests",
  "architecture",
  "conventions",
]);

type KnownKind =
  | "correctness"
  | "security"
  | "performance"
  | "style"
  | "tests"
  | "architecture"
  | "conventions";

function isKnown(kind: string): kind is KnownKind {
  return KNOWN_KINDS.has(kind);
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
  const { t } = useTranslation();
  const type = t(`category.${category}`);

  /* Прогоны, снятые до появления специализаций, несут прежние имена. */
  const kind = producerName.replace(/^reviewer:/, "");
  const reviewer = isKnown(kind) ? t(`category.${kind}`) : kind;

  return (
    <>
      {t("finding.type", { type })}
      {reviewer === type ? null : (
        <>
          <span className="mx-2 opacity-40">·</span>
          {t("finding.reviewer", { reviewer })}
        </>
      )}
    </>
  );
}
