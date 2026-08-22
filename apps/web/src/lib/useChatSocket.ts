import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { ChatEvent } from "@/api/types";

const RECONNECT_DELAY_MS = 1500;

export type ChatConnection = "connecting" | "open";

interface Options {
  onEvent: (event: ChatEvent) => void;
  onReconnect?: () => void;
}

/**
 * Соединение разговора: одно на всю беседу, с восстановлением.
 *
 * Сокет живёт весь разговор, а не один вопрос, и потому обязан переживать
 * обрыв: сервер закрывает его при отказе, сеть — сама по себе, — а человек
 * видит только то, что кнопка перестала работать.
 *
 * Вопрос, заданный до того, как соединение готово, не теряется: он ждёт
 * открытия и уходит первым. Молча проглоченное нажатие — худший из ответов,
 * потому что человек не понимает, спросил он или нет.
 *
 * Обработчики снимаются раньше закрытия. Иначе `onclose` уже ненужного
 * сокета приходит после того, как открылся новый, и гасит его состояние:
 * в разработке React монтирует подписку дважды, и связь оказывается живой,
 * а поле ввода — заблокированным.
 */
export function useChatSocket(conversationId: string, { onEvent, onReconnect }: Options) {
  const [connection, setConnection] = useState<ChatConnection>("connecting");
  const socket = useRef<WebSocket | null>(null);
  const pending = useRef<string | null>(null);
  const hasConnected = useRef(false);
  const handlers = useRef({ onEvent, onReconnect });

  useEffect(() => {
    handlers.current = { onEvent, onReconnect };
  });

  useEffect(() => {
    let isCurrent = true;
    let retry: number | undefined;

    const flush = (live: WebSocket) => {
      const question = pending.current;
      if (question === null) {
        return;
      }
      pending.current = null;
      live.send(JSON.stringify({ question }));
    };

    const connect = () => {
      const live = api.chatStream(conversationId);
      socket.current = live;

      live.onopen = () => {
        if (!isCurrent) {
          return;
        }
        setConnection("open");
        if (hasConnected.current) {
          handlers.current.onReconnect?.();
        }
        hasConnected.current = true;
        flush(live);
      };

      live.onmessage = (message) => {
        if (!isCurrent) {
          return;
        }
        handlers.current.onEvent(JSON.parse(message.data as string) as ChatEvent);
      };

      live.onclose = () => {
        if (!isCurrent) {
          return;
        }
        setConnection("connecting");
        retry = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };
    };

    connect();

    return () => {
      isCurrent = false;
      window.clearTimeout(retry);

      const live = socket.current;
      socket.current = null;
      if (live) {
        live.onopen = null;
        live.onmessage = null;
        live.onclose = null;
        live.close();
      }
    };
  }, [conversationId]);

  const ask = useCallback((question: string) => {
    const live = socket.current;
    if (live && live.readyState === WebSocket.OPEN) {
      live.send(JSON.stringify({ question }));
      return;
    }
    pending.current = question;
  }, []);

  return { connection, ask };
}
