// Заглушка загрузки (Skeleton).
// Назначение: показывать структуру контента, пока данные не загружены, чтобы
// интерфейс не «прыгал» и пользователь понимал, что идёт загрузка.
// Место в архитектуре: примитив UI дизайн-системы.
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Анимированный блок-заглушка.
 *
 * @param props Свойства `<div>`; размеры задаются классами (h-4, w-full).
 * @returns Блок-заглушка, скрытый от скринридеров (`aria-hidden`), чтобы
 *   вспомогательные технологии не читали «пустышку».
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("bg-muted animate-pulse rounded-md", className)}
      {...props}
    />
  );
}

export { Skeleton };
