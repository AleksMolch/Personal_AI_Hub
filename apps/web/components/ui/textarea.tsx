// Многострочное поле ввода.
// Назначение: ввод длинного текста (сообщения чата, SQL-запросы, инструкции).
// Место в архитектуре: примитив UI дизайн-системы.
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Многострочное текстовое поле.
 *
 * @param props Свойства `<textarea>`.
 * @returns Стилизованная textarea.
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-input bg-background flex min-h-16 w-full rounded-md border px-3 py-2 text-sm shadow-xs transition-colors",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "field-sizing-content",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
