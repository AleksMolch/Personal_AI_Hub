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

/** Заголовок карточки. */
function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      data-slot="card-title"
      className={cn("text-pah-lg leading-none font-semibold", className)}
      {...props}
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
