"use client";

// Список источников под ответом ассистента.
//
// Назначение: показать, на какие страницы опирался ответ, и дать возможность
// открыть их. Нумерация совпадает с маркерами `[n]` в тексте ответа, поэтому
// пользователь может сопоставить утверждение и источник.
//
// Место в архитектуре: презентационный компонент чата. Источники приходят из
// снимка сообщения (`model_snapshot.web_search.citations`), сформированного
// backend'ом при веб-поиске.
//
// Безопасность: ссылки открываются в новой вкладке с `rel="noopener
// noreferrer"`. Текст источника выводится как текст (React экранирует HTML),
// поэтому разметка со страницы не может внедриться в интерфейс.
import { ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Источник, как он сохранён в снимке сообщения. */
export interface WebSource {
  index: number;
  title: string;
  url: string;
  snippet?: string;
}

interface WebSourcesProps {
  /** Найденные источники в порядке нумерации. */
  sources: WebSource[];
  /** Предупреждение поиска (например, часть движков не ответила). */
  warning?: string | null;
  /** Дополнительные классы. */
  className?: string;
}

/**
 * Блок «Источники» под ответом.
 *
 * @param props Источники и необязательное предупреждение.
 * @returns Список ссылок с номерами или null, если источников нет.
 */
export function WebSources({ sources, warning, className }: WebSourcesProps) {
  if (sources.length === 0 && !warning) return null;

  return (
    <div className={cn("mt-3 space-y-2", className)}>
      <p className="text-muted-foreground text-pah-sm font-medium">
        Источники веб-поиска
      </p>

      {warning && (
        <p className="text-warning text-pah-xs" role="status">
          {warning}
        </p>
      )}

      <ol className="grid gap-1.5">
        {sources.map((source) => (
          <li key={`${source.index}-${source.url}`}>
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:bg-accent focus-visible:bg-accent flex items-start gap-2 rounded-md border p-2 transition-colors"
            >
              <Badge
                variant="secondary"
                className="mt-0.5 shrink-0 text-pah-xs"
                aria-hidden="true"
              >
                {source.index}
              </Badge>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1">
                  <span className="truncate text-pah-sm font-medium">
                    {source.title}
                  </span>
                  <ExternalLink
                    className="text-muted-foreground size-3 shrink-0"
                    aria-hidden="true"
                  />
                </span>
                <span className="text-muted-foreground block truncate text-pah-xs">
                  {source.url}
                </span>
              </span>
              <span className="sr-only">Откроется в новой вкладке</span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}
