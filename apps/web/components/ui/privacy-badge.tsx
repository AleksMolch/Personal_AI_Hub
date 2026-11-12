// Бейдж режима обработки запроса.
//
// Назначение: честно показывать, как обработаны данные — во внешнем облаке,
// в защищённом гибриде (наружу ушёл только очищенный текст) или локально на
// хосте приложения. Это ключевая ценность продукта, поэтому подсказка
// формулируется без маркетинга и не обещает анонимности.
//
// Место в архитектуре: примитив представления, используется в сообщениях чата
// и в списке провайдеров. Не принимает решений о маршрутизации — только
// отображает уже сохранённый факт (`messages.protection.mode`).
import { Cloud, Shield, ShieldCheck, Unlock } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Режим обработки запроса. */
export type PrivacyMode = "direct" | "cloud" | "hybrid" | "local";

interface PrivacyBadgeProps {
  /** Где обрабатывался запрос. */
  mode: PrivacyMode;
  /** В гибриде: ответ восстановлен из vault на хосте приложения. */
  restored?: boolean;
  /** Размер бейджа: `sm` для строки сообщения, `md` для инспектора. */
  size?: "sm" | "md";
  /** Дополнительные классы. */
  className?: string;
}

/** Подписи и пояснения по режимам. */
const MODE_META: Record<
  PrivacyMode,
  { text: string; tooltip: string; icon: typeof Cloud }
> = {
  direct: {
    text: "Прямой доступ",
    tooltip:
      "Локальные проверки отключены: текст ушёл провайдеру как есть. Так стоит делать только там, где нет чувствительных данных.",
    icon: Unlock,
  },
  cloud: {
    text: "Облако",
    tooltip:
      "Запрос отправлен внешнему AI-провайдеру целиком. Оплата идёт по вашему ключу.",
    icon: Cloud,
  },
  hybrid: {
    text: "Гибрид",
    tooltip:
      "Внешняя модель получила только очищенный текст с псевдонимами. Исходные значения остались на сервере приложения.",
    icon: ShieldCheck,
  },
  local: {
    text: "Локально",
    tooltip:
      "Запрос обработан локальным провайдером (LM Studio/Ollama) и не покидал хост приложения.",
    icon: Shield,
  },
};

/**
 * Бейдж «Облако» / «Гибрид» / «Локально» с пояснением в подсказке.
 *
 * @param props Режим обработки, признак локального восстановления, размер.
 * @returns Бейдж с иконкой; при наведении и фокусе показывает пояснение.
 */
export function PrivacyBadge({
  mode,
  restored = false,
  size = "md",
  className,
}: PrivacyBadgeProps) {
  const meta = MODE_META[mode];
  const Icon = meta.icon;
  // Локальный режим и гибрид защищают данные сильнее облака, поэтому
  // используют зелёный акцент; облако остаётся нейтральным, а «прямой доступ»
  // намеренно не зелёный: отсутствие проверок — не защита.
  const isProtected = mode === "hybrid" || mode === "local";
  const isDirect = mode === "direct";
  const tooltip =
    mode === "hybrid" && restored
      ? `${meta.tooltip} Ответ восстановлен локально и не отправлялся обратно.`
      : meta.tooltip;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant={isProtected ? "default" : "secondary"}
            className={cn(
              "cursor-help gap-1 font-medium",
              isProtected &&
                "bg-privacy-badge text-privacy-badge-foreground hover:bg-privacy-badge/90",
              isDirect &&
                "border-warning/50 bg-warning/10 text-warning hover:bg-warning/15",
              size === "sm" && "px-1.5 py-0 text-pah-xs",
              className,
            )}
          >
            <Icon className={size === "sm" ? "size-3" : "size-3.5"} />
            {meta.text}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs">{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
