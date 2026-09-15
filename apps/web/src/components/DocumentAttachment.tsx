import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { AttachedDocument } from "@/api/types";

interface Props {
  conversationId: string;
  document: AttachedDocument | null;
}

const ACCEPTED = ".md,.txt,.html,.htm";
const MAX_BYTES = 400_000;

/**
 * Документ, приложенный к разговору.
 *
 * Файл читает браузер и отправляет текстом: сервер не принимает двоичного
 * и не разбирает форматов (D-025). Отсюда и перечень — разметка и текст,
 * то есть выгрузка из вики; PDF и DOCX потребовали бы разбора на сервере.
 *
 * Пока документ приложен, разговор идёт только через локальную модель,
 * и об этом сказано здесь же: человек прикладывает требование, не читая
 * решений в документации.
 */
export function DocumentAttachment({ conversationId, document }: Props) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement | null>(null);
  const [problem, setProblem] = useState("");
  const { t } = useTranslation();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    void queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  const attach = useMutation({
    mutationFn: ({ name, text }: { name: string; text: string }) =>
      api.attachDocument(conversationId, name, text),
    onSuccess: refresh,
    onError: (error: Error) => setProblem(error.message),
  });

  const detach = useMutation({
    mutationFn: () => api.detachDocument(conversationId),
    onSuccess: refresh,
  });

  const read = async (file: File) => {
    setProblem("");
    if (file.size > MAX_BYTES) {
      setProblem(t("document.tooLarge"));
      return;
    }
    attach.mutate({ name: file.name, text: await file.text() });
  };

  if (document) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="attachment-chip">
          <span className="text-brass">{t("document.label")}</span>
          <span className="truncate">{document.name}</span>
          <span className="case-label">
            {t("document.size", { size: Math.round(document.size / 1024) })}
          </span>
        </span>
        <button
          type="button"
          onClick={() => detach.mutate()}
          disabled={detach.isPending}
          className="action-quiet"
        >
          {t("document.detach")}
        </button>
        <span className="case-label">{t("document.localOnly")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        ref={input}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file) {
            void read(file);
          }
        }}
      />
      <button
        type="button"
        onClick={() => input.current?.click()}
        disabled={attach.isPending}
        className="action-quiet"
      >
        {attach.isPending ? t("document.attaching") : t("document.attach")}
      </button>
      <span className="case-label">{t("document.formats")}</span>
      {problem ? <span className="text-[13px] text-critical">{problem}</span> : null}
    </div>
  );
}
