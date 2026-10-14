// Заголовок страницы.
//
// Назначение: единый корневой заголовок для страниц, которые строят раскладку
// сами и не используют `AppShell` (полноэкранный чат). Существует ради
// доступности: axe проверяет порядок заголовков (`heading-order`), а страница
// без `h1` лишает пользователя скринридера ориентира и точки перехода.
//
// Место в архитектуре: примитив представления; уровень задаётся вызывающим,
// чтобы вложенные заголовки шли по возрастанию без пропусков.
import * as React from "react";

import { cn } from "@/lib/utils";

interface PageHeadingProps extends React.ComponentProps<"h1"> {
  /** Уровень заголовка: 1 (по умолчанию) … 6. */
  level?: 1 | 2 | 3 | 4 | 5 | 6;
}

/**
 * Заголовок страницы или секции.
 *
 * @param props Свойства заголовка плюс `level`.
 * @returns Элемент заголовка выбранного уровня с типографикой дизайн-системы.
 */
export function PageHeading({
  className,
  level = 1,
  ...props
}: PageHeadingProps) {
  const Heading = `h${level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

  return (
    <Heading
      className={cn(
        level === 1
          ? "text-pah-2xl font-semibold tracking-tight"
          : "text-pah-lg font-semibold",
        className,
      )}
      {...props}
    />
  );
}
