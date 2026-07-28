import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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
        aria-label={`Удалить репозиторий ${name}`}
        className="case-label shrink-0 text-paper-dim transition-colors hover:text-dismissed"
      >
        убрать из архива
      </button>
    );
  }

  return (
    <span className="flex shrink-0 items-center gap-2">
      <span className="case-label text-dismissed">вместе с делами и индексом?</span>
      <button
        type="button"
        onClick={() => remove.mutate()}
        disabled={remove.isPending}
        className="case-label text-dismissed underline underline-offset-2 disabled:opacity-50"
      >
        {remove.isPending ? "убираю…" : "да"}
      </button>
      <button
        type="button"
        onClick={() => setIsConfirming(false)}
        className="case-label text-paper-dim hover:text-paper"
      >
        нет
      </button>
    </span>
  );
}
