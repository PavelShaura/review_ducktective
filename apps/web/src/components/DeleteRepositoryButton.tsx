import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";

interface Props {
  repositoryId: string;
  name: string;
}

/**
 * Удаление репозитория из архива.
 *
 * Подтверждение спрашивается прямо в кнопке, а не в диалоге: вместе
 * с репозиторием уходят его индекс и все дела с находками, и случайное
 * нажатие стоит слишком дорого, чтобы полагаться на «отменить».
 */
export function DeleteRepositoryButton({ repositoryId, name }: Props) {
  const queryClient = useQueryClient();
  const [isConfirming, setIsConfirming] = useState(false);
  const { t } = useTranslation();

  const remove = useMutation({
    mutationFn: () => api.deleteRepository(repositoryId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["repositories"] });
    },
  });

  if (!isConfirming) {
    return (
      <button
        type="button"
        onClick={() => setIsConfirming(true)}
        aria-label={t("deleteRepository.ariaLabel", { name })}
        className="case-label shrink-0 text-paper-dim transition-colors hover:text-dismissed"
      >
        {t("deleteRepository.remove")}
      </button>
    );
  }

  return (
    <span className="flex shrink-0 items-center gap-2">
      <span className="case-label text-dismissed">{t("deleteRepository.confirm")}</span>
      <button
        type="button"
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
        className="case-label text-dismissed underline underline-offset-2 disabled:opacity-50"
      >
        {remove.isPending ? t("deleteRepository.removing") : t("common.yes")}
      </button>
      <button
        type="button"
        onClick={() => setIsConfirming(false)}
        className="case-label text-paper-dim hover:text-paper"
      >
        {t("common.no")}
      </button>
    </span>
  );
}
