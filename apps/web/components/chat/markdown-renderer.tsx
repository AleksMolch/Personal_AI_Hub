"use client";

// Рендерер Markdown для ответов ассистента.
//
// Назначение: безопасно отображать Markdown (абзацы, списки, таблицы, код,
// ссылки) и давать возможность скопировать блок кода одной кнопкой.
// Место в архитектуре: презентационный компонент чата; не выполняет запросы и
// не доверяет содержимому ответа.
//
// Безопасность: `rehype-raw` НЕ подключён намеренно. Ответ модели — это
// недоверенный ввод, а rehype-raw разрешает сырой HTML, что открывает путь к
// XSS. Без него react-markdown экранирует HTML, а ссылки дополнительно
// помечаются rel="noopener noreferrer".
import { useState } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface MarkdownRendererProps {
  /** Markdown-текст ответа. */
  content: string;
  /** Дополнительные классы контейнера. */
  className?: string;
}

/**
 * Блок кода с кнопкой копирования.
 *
 * @param props Класс языка (из `className` вида `language-ts`) и содержимое.
 * @returns `<pre>` с подсветкой-заглушкой и кнопкой копирования.
 */
function CodeBlock({
  className,
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const match = /language-(\w+)/.exec(className ?? "");
  const language = match ? match[1] : "";
  const code = String(children ?? "").replace(/\n$/, "");

  /** Копирует код в буфер обмена и на 2 секунды показывает подтверждение. */
  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Буфер обмена может быть недоступен (нет прав/не HTTPS) — молча
      // игнорируем: копирование не является критичным действием.
    }
  }

  return (
    <div className="group relative my-3">
      {language && (
        <span className="text-muted-foreground absolute top-2 left-3 font-mono text-pah-xs">
          {language}
        </span>
      )}
      <Button
        type="button"
        size="icon-sm"
        variant="ghost"
        onClick={handleCopy}
        aria-label={copied ? "Скопировано" : "Скопировать код"}
        className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
      >
        {copied ? <Check /> : <Copy />}
      </Button>
      <pre className="bg-muted overflow-x-auto rounded-md border p-3 pt-7 text-pah-sm">
        <code className={cn("font-mono", className)}>{code}</code>
      </pre>
    </div>
  );
}

/**
 * Рендерит Markdown-ответ ассистента.
 *
 * @param props Текст ответа и дополнительные классы.
 * @returns Разметку Markdown со стилями дизайн-системы.
 */
export function MarkdownRenderer({
  content,
  className,
}: MarkdownRendererProps) {
  return (
    <div
      className={cn(
        "text-pah-base leading-relaxed",
        // Типографика вложенных элементов задаётся здесь, чтобы не тянуть
        // плагин typography и не зависеть от ещё одной конфигурации.
        "[&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
        "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
        "[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
        "[&_li]:my-1",
        "[&_h1]:mt-4 [&_h1]:text-pah-xl [&_h1]:font-semibold",
        "[&_h2]:mt-4 [&_h2]:text-pah-lg [&_h2]:font-semibold",
        "[&_h3]:mt-3 [&_h3]:font-semibold",
        "[&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-pah-sm",
        "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-4",
        "[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-pah-sm",
        "[&_th]:border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_th]:text-left",
        "[&_td]:border [&_td]:px-2 [&_td]:py-1",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // react-markdown вызывает `code` и для инлайна, и для блоков; блоки
          // отличаем по наличию language-класса или переноса строки.
          code({ className: codeClassName, children, ...rest }) {
            const isBlock =
              /language-\w+/.test(codeClassName ?? "") ||
              String(children ?? "").includes("\n");
            if (!isBlock) {
              return (
                <code className={codeClassName} {...rest}>
                  {children}
                </code>
              );
            }
            return <CodeBlock className={codeClassName}>{children}</CodeBlock>;
          },
          pre({ children }) {
            // Внешний <pre> из react-markdown не нужен: CodeBlock рисует свой,
            // иначе получается двойная рамка и лишние отступы.
            return <>{children}</>;
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
