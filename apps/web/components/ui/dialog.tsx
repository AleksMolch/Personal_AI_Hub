// Модальное окно (Dialog).
// Назначение: онбординг, подтверждения, формы в оверлее.
// Место в архитектуре: примитив UI на базе Radix Dialog. Radix обеспечивает
// захват фокуса, закрытие по Escape и блокировку скролла фона.
//
// Отличие от стандартного shadcn: DialogContent принимает `hideClose`, чтобы
// можно было запретить закрытие шага онбординга (в шрифтовом наборе гайда этот
// проп использован, но в shadcn его нет).
"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { XIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Корень диалога: управляет открытием (`open`). */
function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

/** Кнопка/элемент, открывающий диалог. */
function DialogTrigger(
  props: React.ComponentProps<typeof DialogPrimitive.Trigger>,
) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

/** Портал, выносящий диалог в конец документа. */
function DialogPortal(
  props: React.ComponentProps<typeof DialogPrimitive.Portal>,
) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

/** Кнопка закрытия диалога. */
function DialogClose(
  props: React.ComponentProps<typeof DialogPrimitive.Close>,
) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

/** Затемнение фона под диалогом. */
function DialogOverlay({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/50 backdrop-blur-xs",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Содержимое диалога.
 *
 * @param props Свойства Radix Content плюс `hideClose`.
 *   `hideClose` убирает крестик и запрещает закрытие по Escape/клику по фону —
 *   используется в онбординге, где шаг нельзя пропустить случайно.
 * @returns Панель диалога с заголовком и содержимым.
 */
function DialogContent({
  className,
  children,
  hideClose = false,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  hideClose?: boolean;
}) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        onEscapeKeyDown={(event) => {
          if (hideClose) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (hideClose) event.preventDefault();
        }}
        className={cn(
          "bg-background fixed top-1/2 left-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-lg border p-6 shadow-lg",
          "max-h-[90vh] overflow-y-auto",
          "data-[state=open]:animate-in data-[state=closed]:animate-out",
          "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
          "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95",
          className,
        )}
        {...props}
      >
        {children}
        {!hideClose && (
          <DialogPrimitive.Close
            data-slot="dialog-close-button"
            className={cn(
              "ring-offset-background absolute top-4 right-4 rounded-sm opacity-70 transition-opacity",
              "hover:opacity-100 focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
              "disabled:pointer-events-none",
            )}
          >
            <XIcon className="size-4" />
            <span className="sr-only">Закрыть</span>
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

/** Шапка диалога. */
function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn("flex flex-col gap-1.5 text-left", className)}
      {...props}
    />
  );
}

/** Подвал диалога для кнопок действий. */
function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-col-reverse gap-2 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    />
  );
}

/** Заголовок диалога (связывается с содержимым для скринридеров). */
function DialogTitle({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-pah-xl leading-none font-semibold", className)}
      {...props}
    />
  );
}

/** Описание диалога. */
function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-muted-foreground text-sm", className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
};
