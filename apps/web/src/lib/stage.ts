import type { TFunction } from "i18next";

import type { IndexState } from "@/api/types";

/**
 * Название стадии сборки на языке интерфейса.
 *
 * Сервер присылает и код стадии, и её название, но название — на своём
 * языке; интерфейс подписывает стадию сам по коду и на сервер за словами
 * не ходит.
 */
export function stageTitle(
  t: TFunction,
  state: Pick<IndexState, "stage" | "stage_title"> | undefined,
): string | null {
  if (!state) {
    return null;
  }
  if (state.stage) {
    return t(`index.stageTitle.${state.stage}`);
  }
  return state.stage_title;
}
