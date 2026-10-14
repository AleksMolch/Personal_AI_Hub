// Компоненты карточки (контейнер контента).
// Назначение: единый контейнер для блоков интерфейса (формы, метрики, списки).
// Место в архитектуре: примитив UI без состояния и логики.
import * as React from "react";

import { cn } from "@/lib/utils";

/** Внешний контейнер карточки. */
function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card"
      className={cn(
        "bg-card text-card-foreground flex flex-col gap-4 rounded-lg border py-4 shadow-xs",
        className,
      )}
      {...props}
    />
  );
}

/** Шапка карточки: заголовок и описание. */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn("flex flex-col gap-1 px-4", className)}
      {...props}
    />
  );
}

/**
 * Заголовок карточки.
 *
 * Уровень заголовка настраивается: axe проверяет порядок заголовков
 * (`heading-order`), и на странице, где перед карточкой стоит `h1`, уровень
 * `h3` создаёт пропуск. По умолчанию `h2` — корректный уровень для карточки
 * сразу под заголовком страницы.
 *
 * @param props Свойства заголовка плюс `level` (2..6).
 * @returns Элемент заголовка нужного уровня.
 */
function CardTitle({
  className,
  level = 2,
  ...props
}: React.ComponentProps<"h2"> & {
  /** Уровень заголовка: 2 (по умолчанию) … 6. */
  level?: 2 | 3 | 4 | 5 | 6;
}) {
  const Heading = `h${level}` as "h2" | "h3" | "h4" | "h5" | "h6";

  return (
    <Heading
      data-slot="card-title"
      className={cn("text-pah-lg leading-none font-semibold", className)}
      {...(props as React.ComponentProps<"h2">)}
    />
  );
}

/** Пояснение под заголовком карточки. */
function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="card-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  );
}

/** Содержимое карточки. */
function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("px-4", className)}
      {...props}
    />
  );
}

/** Подвал карточки для действий. */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn("flex items-center px-4", className)}
      {...props}
    />
  );
}

export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
};
