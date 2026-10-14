"use client";

// Список сообщений диалога с виртуализацией.
//
// Назначение: отображать длинные диалоги без просадки производительности.
// При сотнях сообщений рендер всего списка замедляет ввод и скролл, поэтому
// список виртуализируется (react-virtuoso монтирует только видимые элементы).
//
// Место в архитектуре: презентационный компонент чата; получает готовые
// сообщения и обработчики.
//
// Доступность: контейнер помечен role="log" и aria-live, чтобы новый ответ
// объявлялся один раз; aria-busy сообщает скринридеру о ходе генерации.
import { useEffect, useRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";

import { ChatMessage, type ChatMessageView } from "@/components/chat/message";

interface MessageListProps {
  /** Сообщения диалога в хронологическом порядке. */
  messages: ChatMessageView[];
  /** Текст текущего потокового ответа (ещё не сохранён в истории). */
  streamingContent?: string;
  /** Идёт ли генерация. */
  isStreaming?: boolean;
  /** Повторить генерацию для указанного ответа. */
  onRegenerate?: (messageId: string) => void;
}

/**
 * Виртуализированный список сообщений.
 *
 * @param props Сообщения, текущий поток и обработчик повтора.
 * @returns Прокручиваемый список; автоматически доскролливает вниз при
 *   появлении новых данных и во время стриминга.
 */
export function MessageList({
  messages,
  streamingContent,
  isStreaming,
  onRegenerate,
}: MessageListProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);

  // Виртуализация не следит за «внешним» растущим текстом, поэтому во время
  // стриминга доскролливаем вниз вручную на каждом обновлении.
  useEffect(() => {
    if (isStreaming) {
      virtuosoRef.current?.scrollToIndex({
        index: Number.MAX_SAFE_INTEGER,
        behavior: "auto",
      });
    }
  }, [streamingContent, isStreaming]);

  // Стримящийся ответ показываем отдельным элементом поверх истории: он ещё
  // не имеет серверного идентификатора.
  const items: ChatMessageView[] = isStreaming
    ? [
        ...messages,
        {
          id: "streaming",
          role: "assistant",
          content: streamingContent ?? "",
          isStreaming: true,
          status: "streaming",
        },
      ]
    : messages;

  return (
    <div
      className="min-h-0 flex-1"
      role="log"
      aria-label="Сообщения диалога"
      aria-busy={isStreaming || undefined}
    >
      <Virtuoso
        ref={virtuosoRef}
        data={items}
        className="h-full"
        followOutput="smooth"
        initialTopMostItemIndex={Math.max(0, items.length - 1)}
        itemContent={(_index, item) => (
          <ChatMessage
            key={item.id}
            message={item}
            onRegenerate={
              onRegenerate && !item.isStreaming
                ? () => onRegenerate(item.id)
                : undefined
            }
          />
        )}
      />
    </div>
  );
}
