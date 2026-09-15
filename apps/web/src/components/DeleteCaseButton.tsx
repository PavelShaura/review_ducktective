import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

interface Props {
  runId: string;
  repositoryId: string;
}

/**
 * Подтверждение спрашивается на месте, а не в модальном окне: вместе с делом
 * удаляется его разметка, и случайный клик стоит дорого.
 */
export function DeleteCaseButton({ runId, repositoryId }: Props) {
  const [isConfirming, setIsConfirming] = useState(false);
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const remove = useMutation({
    mutationFn: () => api.deleteRun(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs", repositoryId] }),
  });

  if (remove.isError) {
    return (
      <span className="font-mono text-[12px] text-critical">{t("deleteCase.failed")}</span>
    );
  }

  if (!isConfirming) {
    return (
      <button
        type="button"
        onClick={() => setIsConfirming(true)}
        className="rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] text-paper-dim transition-colors hover:border-critical hover:text-critical"
      >
        {t("deleteCase.delete")}
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2">
      <span className="case-label">{t("deleteCase.confirm")}</span>
      <button
        type="button"
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
        className="rounded-case border border-critical px-3 py-1 font-mono text-[12px] text-critical transition-colors hover:bg-critical hover:text-ink disabled:opacity-50"
      >
        {remove.isPending ? t("deleteCase.deleting") : t("common.yes")}
      </button>
      <button
        type="button"
        onClick={() => setIsConfirming(false)}
        className="rounded-case border border-tweed-dim px-3 py-1 font-mono text-[12px] text-paper-dim transition-colors hover:border-tweed hover:text-paper"
      >
        {t("common.no")}
      </button>
    </span>
  );
}
