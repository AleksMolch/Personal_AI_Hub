// Бейдж стоимости запроса.
//
// Назначение: показывать пользователю, сколько стоил запрос и является ли эта
// цифра фактом или оценкой. Это центральная ценность продукта (экономическая
// дисциплина), поэтому оценка НИКОГДА не должна выглядеть как факт.
//
// Место в архитектуре: примитив представления, источник данных — UsageRecord
// (`cost_amount` Decimal-строкой, `cost_state`) и units_json (токены).
//
// Отличия от примера в UI-гайде (исправленные дефекты):
// 1. Классы цветов заданы статическими строками, а не шаблоном
//    `text-${color}`: Tailwind собирает классы статически и динамическую
//    интерполяцию не увидит, поэтому такие классы просто не попадут в CSS.
// 2. Валюта не зашита как «₽»: проект считает в валюте бюджета (по умолчанию
//    USD) и конвертирует через FxRate, поэтому символ приходит снаружи.
// 3. Поддержан `cost_state`, который есть в backend: estimated, actual,
//    reconciled, unknown. Reconciled показывается как факт (сверено).
import { CircleHelp, Coins } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** Состояние расчёта стоимости (соответствует CostState в backend). */
export type CostStatus = "estimated" | "actual" | "reconciled" | "unknown";

/** Пороги «дёшево / средне / дорого» в валюте бюджета. */
export interface CostThresholds {
  /** Стоимость ниже этого значения считается низкой. */
  low: number;
  /** Стоимость ниже этого значения считается средней, выше — высокой. */
  medium: number;
}

/** Пороги по умолчанию для валюты бюджета (USD). */
export const DEFAULT_COST_THRESHOLDS: CostThresholds = {
  low: 0.01,
  medium: 0.1,
};

// Статическая карта классов: Tailwind видит эти строки целиком при сборке.
const COST_CLASSES = {
  low: "text-cost-low border-cost-low",
  medium: "text-cost-medium border-cost-medium",
  high: "text-cost-high border-cost-high",
} as const;

interface CostBadgeProps {
  /** Стоимость как Decimal-строка или число. */
  cost?: string | number | null;
  /** Символ или код валюты бюджета (например, $ или USD). */
  currency?: string;
  /** Состояние расчёта стоимости. */
  status?: CostStatus;
  /** Число входных токенов для подсказки. */
  tokensIn?: number;
  /** Число выходных токенов для подсказки. */
  tokensOut?: number;
  /** Токены рассуждений (входят в выходные, показываются отдельно). */
  reasoningTokens?: number;
  /** Размер бейджа. */
  size?: "sm" | "md";
  /** Пороги окраски под валюту бюджета. */
  thresholds?: CostThresholds;
  /** Дополнительные классы. */
  className?: string;
}

/**
 * Форматирует стоимость с фиксированной точностью.
 *
 * @param value Стоимость.
 * @returns Строка вида `0.0123`; очень малые значения не округляются в ноль
 *   без следа (показываются как `<0.0001`).
 */
function formatCost(value: number): string {
  if (value === 0) return "0";
  if (value < 0.0001) return "<0.0001";
  if (value < 1) return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return value.toFixed(2);
}

/**
 * Выбирает цветовой класс по величине стоимости.
 *
 * @param value Стоимость.
 * @param thresholds Пороги в валюте бюджета.
 * @returns Класс из статической карты COST_CLASSES.
 */
function pickCostClass(value: number, thresholds: CostThresholds): string {
  if (value < thresholds.low) return COST_CLASSES.low;
  if (value < thresholds.medium) return COST_CLASSES.medium;
  return COST_CLASSES.high;
}

/**
 * Бейдж стоимости запроса с пояснением в подсказке.
 *
 * @param props Стоимость, валюта, состояние расчёта, токены и пороги.
 * @returns Бейдж с иконкой; для отсутствующей цены — «Цена не задана».
 *   Оценка помечается знаком «≈» и пунктирной рамкой, факт — сплошной.
 */
export function CostBadge({
  cost,
  currency = "$",
  status = "actual",
  tokensIn,
  tokensOut,
  reasoningTokens,
  size = "md",
  thresholds = DEFAULT_COST_THRESHOLDS,
  className,
}: CostBadgeProps) {
  const numeric = typeof cost === "string" ? Number(cost) : cost;
  const hasCost =
    numeric !== null && numeric !== undefined && !Number.isNaN(numeric);
  const sizeClass = size === "sm" ? "px-1.5 py-0 text-pah-xs" : undefined;

  // Цена неизвестна: модель без PriceSnapshot либо запрос без usage-оценки.
  if (status === "unknown" || !hasCost) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge
              variant="outline"
              className={cn(
                "text-cost-unknown border-cost-unknown cursor-help gap-1",
                sizeClass,
                className,
              )}
            >
              <CircleHelp className={size === "sm" ? "size-3" : "size-3.5"} />
              Цена не задана
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            <p>
              Для этой модели не настроена стоимость.
              <br />
              Запрос не учитывается в бюджете.
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  const isEstimated = status === "estimated";
  const iconSize = size === "sm" ? "size-3" : "size-3.5";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge
            variant="outline"
            className={cn(
              "cursor-help gap-1 font-medium",
              pickCostClass(numeric, thresholds),
              isEstimated && "border-dashed",
              sizeClass,
              className,
            )}
          >
            <Coins className={iconSize} />
            {isEstimated && "≈"}
            {formatCost(numeric)} {currency}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <div className="space-y-0.5 text-sm">
            <p className="font-medium">
              {isEstimated
                ? "Ориентировочная оценка (провайдер не вернул usage)"
                : status === "reconciled"
                  ? "Стоимость сверена с провайдером"
                  : "Расчёт по usage провайдера"}
            </p>
            {tokensIn !== undefined && (
              <p>Вход: {tokensIn.toLocaleString("ru-RU")} токенов</p>
            )}
            {tokensOut !== undefined && (
              <p>Выход: {tokensOut.toLocaleString("ru-RU")} токенов</p>
            )}
            {reasoningTokens !== undefined && reasoningTokens > 0 && (
              <p className="text-muted-foreground">
                из них рассуждения: {reasoningTokens.toLocaleString("ru-RU")}
              </p>
            )}
            <p className="text-muted-foreground text-xs">
              {isEstimated
                ? "Точная стоимость станет известна после ответа провайдера."
                : "Это расчёт по токенам и сохранённому прайсу, а не счёт провайдера: тарифы меняются, а у части провайдеров зависят от времени суток (пиковые часы дороже)."}
            </p>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
