// Всплывающая подсказка (Tooltip).
// Назначение: пояснять иконки и бейджи (стоимость, приватность) без занятия
// места на экране.
// Место в архитектуре: примитив UI на базе Radix Tooltip; раскрывается и по
// наведению, и по фокусу с клавиатуры.
"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

/**
 * Провайдер подсказок.
 *
 * @param props Свойства Radix Provider; `delayDuration` управляет задержкой.
 * @returns Контекст для вложенных Tooltip (нужен один на поддерево).
 */
function TooltipProvider({
  delayDuration = 200,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  );
}

/**
 * Корень подсказки.
 *
 * @param props Свойства Radix Tooltip Root.
 * @returns Узел, связывающий триггер и содержимое подсказки.
 */
function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

/**
 * Элемент, при наведении на который показывается подсказка.
 *
 * @param props Свойства Radix Tooltip Trigger; обычно с `asChild`.
 * @returns Триггер подсказки.
 */
function TooltipTrigger(
  props: React.ComponentProps<typeof TooltipPrimitive.Trigger>,
) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

/**
 * Содержимое подсказки.
 *
 * @param props Свойства Radix Tooltip Content; `sideOffset` — отступ.
 * @returns Всплывающая панель с текстом.
 */
function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        className={cn(
          "bg-foreground text-background z-50 w-fit rounded-md px-3 py-1.5 text-xs text-balance shadow-md",
          "animate-in fade-in-0 zoom-in-95",
          className,
        )}
        {...props}
      >
        {children}
        <TooltipPrimitive.Arrow className="bg-foreground fill-foreground z-50 size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px]" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
