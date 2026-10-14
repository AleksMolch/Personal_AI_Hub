// Индикатор выполнения.
// Назначение: показывать прогресс задач (jobs), шагов онбординга, загрузки.
// Место в архитектуре: примитив UI на базе Radix Progress; значение задаётся
// в процентах 0..100 и доступно скринридерам через aria-атрибуты Radix.
"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";

import { cn } from "@/lib/utils";

/**
 * Полоса прогресса.
 *
 * @param props Свойства Radix Progress; `value` — процент 0..100.
 * @returns Полоса прогресса с корректными ARIA-атрибутами.
 */
function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn(
        "bg-secondary relative h-2 w-full overflow-hidden rounded-full",
        className,
      )}
      value={value}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className="bg-primary h-full w-full flex-1 transition-transform"
        style={{ transform: `translateX(-${100 - (value ?? 0)}%)` }}
      />
    </ProgressPrimitive.Root>
  );
}

export { Progress };
