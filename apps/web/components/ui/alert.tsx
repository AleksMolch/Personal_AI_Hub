// Компонент информационного сообщения (Alert).
// Назначение: показывать предупреждения, ошибки и подсказки внутри страницы,
// не блокируя работу пользователя.
// Место в архитектуре: примитив UI. Варианты включают `warning` — он нужен
// ModelPricingWarning (у стандартного shadcn-набора варианта warning нет).
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** Варианты оформления сообщения. */
const alertVariants = cva(
  "relative grid w-full grid-cols-[0_1fr] items-start gap-y-0.5 rounded-lg border px-4 py-3 text-sm has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] has-[>svg]:gap-x-3 [&>svg]:size-4 [&>svg]:translate-y-0.5",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        destructive:
          "border-destructive/40 text-destructive bg-destructive/5 [&>svg]:text-current",
        warning:
          "border-warning/50 text-warning-foreground bg-warning/10 [&>svg]:text-current",
        info: "border-info/40 bg-info/5 [&>svg]:text-current",
        success: "border-success/40 bg-success/5 [&>svg]:text-current",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

/**
 * Контейнер сообщения.
 *
 * @param props Свойства `<div>` плюс `variant`.
 * @returns Блок с ролью alert для объявления скринридером.
 */
function Alert({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      data-slot="alert"
      role="alert"
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}

/**
 * Заголовок сообщения.
 *
 * @param props Свойства `<div>`.
 * @returns Строка заголовка внутри Alert.
 */
function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn(
        "col-start-2 min-h-4 font-medium tracking-tight",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Описание сообщения.
 *
 * @param props Свойства `<div>`.
 * @returns Текст пояснения внутри Alert.
 */
function AlertDescription({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "col-start-2 grid justify-items-start gap-1 text-sm opacity-90 [&_p]:leading-relaxed",
        className,
      )}
      {...props}
    />
  );
}

export { Alert, AlertTitle, AlertDescription, alertVariants };
