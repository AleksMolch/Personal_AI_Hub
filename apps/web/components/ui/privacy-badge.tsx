// Бейдж приватности обработки запроса.
//
// Назначение: честно показывать, где обрабатывались данные — локально на
// машине пользователя или во внешнем AI-провайдере. Это одна из ключевых
// ценностей продукта, поэтому подсказка формулируется без маркетинга.
//
// Место в архитектуре: примитив представления данных, используется в сообщениях
// чата и в инспекторе. Не принимает решений о маршрутизации — только
// отображает уже известный факт.
//
// Важно: на Этапе 1 локального inference нет, поэтому все запросы идут через
// облачного провайдера, и компонент получает mode="cloud". Ветка "local"
// сохранена для Этапа 2 и не должна использоваться, пока backend не начнёт
// реально обрабатывать запросы локально.
import { Cloud, Shield } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Режим обработки запроса. */
export type PrivacyMode = "local" | "cloud";

interface PrivacyBadgeProps {
  /** Где обрабатывался запрос. */
  mode: PrivacyMode;
  /** Размер бейджа: `sm` для строки сообщения, `md` для инспектора. */
  size?: "sm" | "md";
  /** Дополнительные классы. */
  className?: string;
}

/**
 * Бейдж «Локально» / «Облако» с пояснением в подсказке.
 *
 * @param props Режим обработки, размер и дополнительные классы.
 * @returns Бейдж с иконкой; при наведении и фокусе показывает пояснение.
 */
export function PrivacyBadge({
  mode,
  size = "md",
  className,
}: PrivacyBadgeProps) {
  const isLocal = mode === "local";
  const Icon = isLocal ? Shield : Cloud;
  const text = isLocal ? "Локально" : "Облако";
  const tooltip = isLocal
    ? "Данные обработаны на вашем компьютере и не отправлялись во внешние сервисы"
    : "Запрос отправлен во внешний AI-провайдер. Оплата идёт по вашему ключу.";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant={isLocal ? "default" : "secondary"}
            className={cn(
              "cursor-help gap-1 font-medium",
              isLocal &&
                "bg-privacy-badge text-privacy-badge-foreground hover:bg-privacy-badge/90",
              size === "sm" && "px-1.5 py-0 text-pah-xs",
              className,
            )}
          >
            <Icon className={size === "sm" ? "size-3" : "size-3.5"} />
            {text}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
