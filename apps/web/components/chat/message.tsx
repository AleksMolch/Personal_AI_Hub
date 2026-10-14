"use client";

// Сообщение чата с индикаторами стоимости и приватности.
//
// Назначение: отобразить одно сообщение диалога, служебные метки (статус,
// ошибка) и экономические показатели ответа — стоимость, токены, токены
// рассуждений. Это ядро ценностного предложения продукта: пользователь должен
// видеть, сколько стоил каждый ответ и является ли цифра оценкой.
//
// Место в архитектуре: презентационный компонент чата. Данные приходят сверху
// (страница чата), запросы не выполняются.
//
// Доступность: сообщение помечено role="article" и aria-label; во время
// стриминга aria-live выключен (иначе скринридер зачитывает каждый токен), а
// после завершения переключается в "polite" — тогда ответ озвучивается один раз.
import { useState } from "react";
import { Copy, RotateCcw } from "lucide-react";

import { MarkdownRenderer } from "@/components/chat/markdown-renderer";
import { WebSources, type WebSource } from "@/components/chat/web-sources";
import { Button } from "@/components/ui/button";
import { CostBadge, type CostStatus } from "@/components/ui/cost-badge";
import { PrivacyBadge } from "@/components/ui/privacy-badge";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Данные сообщения, необходимые для отображения. */
export interface ChatMessageView {
  /** Идентификатор (для оптимистичных сообщений — временный). */
  id: string;
  /** Роль автора. */
  role: "user" | "assistant";
  /** Текст сообщения (Markdown для ассистента). */
  content: string;
  /** Статус генерации: pending/streaming/completed/failed/cancelled/interrupted. */
  status?: string;
  /** Код ошибки, если генерация не удалась. */
  errorCode?: string | null;
  /** Идёт ли приём токенов прямо сейчас (для aria-live и курсора). */
  isStreaming?: boolean;
  /** Стоимость ответа; отсутствует, если usage ещё не пришёл. */
  cost?: string | null;
  /** Состояние расчёта стоимости. */
  costStatus?: CostStatus;
  /** Валюта бюджета (из /usage/summary). */
  currency?: string;
  /** Входные токены. */
  tokensIn?: number;
  /** Выходные токены. */
  tokensOut?: number;
  /** Токены рассуждений (входят в выходные, показываются отдельно). */
  reasoningTokens?: number;
  /** Источники веб-поиска, если запрос был с веб-доступом. */
  sources?: WebSource[];
  /** Предупреждение поиска (например, часть движков не ответила). */
  searchWarning?: string | null;
}

interface ChatMessageProps {
  /** Данные сообщения. */
  message: ChatMessageView;
  /** Повторить генерацию (доступно только для ответов ассистента). */
  onRegenerate?: () => void;
  /** Дополнительные классы. */
  className?: string;
}

/**
 * Одно сообщение диалога.
 *
 * @param props Сообщение и обработчик повторной генерации.
 * @returns Блок сообщения с метками стоимости/приватности и действиями.
 */
export function ChatMessage({
  message,
  onRegenerate,
  className,
}: ChatMessageProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  // aria-live вычисляется при рендере, а не через эффект: это производное
  // значение, и лишний цикл рендера здесь не нужен.
  const ariaLive: "off" | "polite" = message.isStreaming ? "off" : "polite";

  /** Копирует текст сообщения в буфер обмена. */
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Буфер обмена может быть недоступен — действие не критично.
    }
  }

  const failed = message.status === "failed";

  return (
    <article
      role="article"
      aria-live={ariaLive}
      aria-label={isUser ? "Ваше сообщение" : "Ответ ассистента"}
      className={cn(
        "group border-b px-4 py-5 transition-colors last:border-b-0",
        isUser ? "bg-muted/40" : "bg-background",
        className,
      )}
    >
      <div className="mx-auto flex max-w-3xl gap-3">
        <div
          aria-hidden="true"
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md border text-pah-xs font-medium select-none",
            isUser
              ? "bg-background"
              : "bg-primary text-primary-foreground border-transparent",
          )}
        >
          {isUser ? "Вы" : "ИИ"}
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          {isUser ? (
            <p className="text-pah-base whitespace-pre-wrap">
              {message.content}
            </p>
          ) : (
            <MarkdownRenderer content={message.content} />
          )}

          {message.isStreaming && (
            <span
              className="bg-foreground inline-block h-4 w-1.5 animate-pulse align-middle"
              aria-hidden="true"
            />
          )}

          {failed && (
            <p className="text-destructive text-pah-sm" role="alert">
              Ошибка генерации
              {message.errorCode ? `: ${message.errorCode}` : ""}
            </p>
          )}

          {/* Источники веб-поиска: показываем до меток стоимости, чтобы связь
              «утверждение → ссылка» читалась сразу под ответом. */}
          {!isUser && !message.isStreaming && message.sources && (
            <WebSources
              sources={message.sources}
              warning={message.searchWarning}
            />
          )}

          {/* Метки показываем только у ответов ассистента: у вопроса нет ни
              стоимости, ни режима обработки. */}
          {!isUser && !message.isStreaming && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {/* На Этапе 1 локального inference нет, поэтому все запросы идут
                  через внешнего провайдера — режим всегда "cloud". */}
              <PrivacyBadge mode="cloud" size="sm" />
              <CostBadge
                cost={message.cost ?? undefined}
                currency={message.currency ?? "$"}
                status={message.costStatus ?? "unknown"}
                tokensIn={message.tokensIn}
                tokensOut={message.tokensOut}
                reasoningTokens={message.reasoningTokens}
                size="sm"
              />
              {message.reasoningTokens !== undefined &&
                message.reasoningTokens > 0 && (
                  <Badge variant="outline" className="text-pah-xs">
                    Рассуждения:{" "}
                    {message.reasoningTokens.toLocaleString("ru-RU")}
                  </Badge>
                )}
            </div>
          )}
        </div>

        {!isUser && !message.isStreaming && (
          <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={copy}
              aria-label={copied ? "Скопировано" : "Скопировать ответ"}
            >
              <Copy />
            </Button>
            {onRegenerate && (
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={onRegenerate}
                aria-label="Повторить генерацию"
              >
                <RotateCcw />
              </Button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
