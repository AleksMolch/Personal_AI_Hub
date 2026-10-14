// Подпись поля формы.
// Назначение: связать текст подписи с элементом управления (доступность).
// Место в архитектуре: примитив UI на базе Radix Label.
"use client";

import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";

import { cn } from "@/lib/utils";

/**
 * Подпись к элементу формы.
 *
 * @param props Свойства Radix Label.
 * @returns Элемент label; клик по нему фокусирует связанное поле.
 */
function Label({
  className,
  ...props
}: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm leading-none font-medium select-none",
        "group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
