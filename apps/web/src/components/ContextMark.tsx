import { useTranslation } from "react-i18next";

import type { ReviewRun } from "@/api/types";

interface Props {
  run: ReviewRun;
}

const SETTLED_STATUSES = new Set(["completed", "failed"]);

/**
 * Участвовал ли индекс в этом прогоне.
 *
 * Без окружения ревьюер видит только дифф и находит заметно меньше — на
 * измерениях разница вышла двукратной. Если этого не показать, качество
 * находок выглядит случайностью, а не следствием собранного индекса.
 *
 * Счёт файлов с контекстом записывается вместе с находками, то есть в самом
 * конце. До этого момента ноль означает «ещё не считали», а не «индекса нет»,
 * и говорить о диффе без окружения рано.
 *
 * Прекращённый прогон до этого конца не доходит вовсе: у него ноль остаётся
 * навсегда, и приняв его за ответ, дело заявляло «без индекса» там, где индекс
 * собран и в прошлый раз дал полный охват.
 *
 * Знаменатель приходит с сервера. Считая его здесь, интерфейс делил на число
 * из другого счёта: удалённые файлы модели не отдаются, но в списке остаются,
 * и полный охват выглядел как «13 из 14».
 */
export function ContextMark({ run }: Props) {
  const { t } = useTranslation();
  const reviewable = run.reviewable_files;
  const covered = run.files_with_context;

  if (covered > 0) {
    return (
      <span className="case-label text-confirmed">
        {t("contextMark.withContext", { covered, total: reviewable })}
      </span>
    );
  }

  if (run.status === "cancelled") {
    return <span className="case-label text-paper-dim">{t("contextMark.notCounted")}</span>;
  }

  if (!SETTLED_STATUSES.has(run.status)) {
    return <span className="case-label text-paper-dim">{t("contextMark.collecting")}</span>;
  }

  return (
    <span className="case-label text-paper-dim" title={t("contextMark.noIndexTitle")}>
      {t("contextMark.noIndex")}
    </span>
  );
}
