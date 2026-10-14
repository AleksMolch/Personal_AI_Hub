// Поле ввода.
// Назначение: однострочный ввод в формах и фильтрах.
// Место в архитектуре: примитив UI дизайн-системы.
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Текстовое поле ввода.
 *
 * @param props Свойства `<input>`.
 * @returns Стилизованный input; невалидное состояние даёт `aria-invalid`.
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "border-input bg-background flex h-9 w-full min-w-0 rounded-md border px-3 py-1 text-sm shadow-xs transition-colors",
        "placeholder:text-muted-foreground",
        "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
        "aria-invalid:border-destructive aria-invalid:ring-destructive/20",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "file:text-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
