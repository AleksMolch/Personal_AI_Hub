// Разделитель (Separator).
// Назначение: визуально разделять блоки интерфейса.
// Место в архитектуре: примитив UI на базе Radix Separator.
"use client";

import * as React from "react";
import * as SeparatorPrimitive from "@radix-ui/react-separator";

import { cn } from "@/lib/utils";

/**
 * Линия-разделитель между блоками.
 *
 * @param props Свойства Radix Separator; `orientation` задаёт направление,
 *   `decorative` — декоративный (по умолчанию) или смысловой разделитель.
 * @returns Визуальный разделитель; при `decorative=false` получает роль
 *   separator для скринридеров.
 */
function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      data-slot="separator"
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "bg-border shrink-0",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  );
}

export { Separator };
