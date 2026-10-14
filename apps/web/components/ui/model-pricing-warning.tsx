// Предупреждение о модели без настроенной цены.
//
// Назначение: объяснить, что без PriceSnapshot платный вызов НЕ выполняется.
// Backend работает в strict-режиме: цена обязательна для чата, embeddings
// (индексация и RAG-запрос) и RAG-синтеза, иначе возвращается ошибка
// PRICE_REQUIRED / 400. Поэтому предупреждение не «мягкое»: оно сообщает о
// блокировке, а не о том, что «запрос просто не будет учтён».
//
// Место в архитектуре: представление состояния конфигурации; используется в
// чате при выборе модели и на странице моделей.
import { TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ModelPricingWarningProps {
  /** Отображаемое имя модели. */
  modelName: string;
  /** Переход к настройке цены; если не задан — кнопка не показывается. */
  onSetupPrice?: () => void;
  /** Дополнительные классы. */
  className?: string;
}

/**
 * Встроенное предупреждение «цена не настроена».
 *
 * @param props Имя модели и обработчик перехода к настройке цены.
 * @returns Блок Alert с объяснением блокировки и кнопкой настройки.
 */
export function ModelPricingWarning({
  modelName,
  onSetupPrice,
  className,
}: ModelPricingWarningProps) {
  return (
    <Alert variant="warning" className={cn("border-warning/50", className)}>
      <TriangleAlert />
      <AlertTitle>Цена не настроена — запросы заблокированы</AlertTitle>
      <AlertDescription className="mt-1 space-y-2">
        <p>
          Для модели <strong>{modelName}</strong> нет ни одной записи цены.
        </p>
        <ul className="text-muted-foreground list-inside list-disc space-y-0.5 text-sm">
          <li>
            отправить сообщение не получится: вернётся ошибка PRICE_REQUIRED;
          </li>
          <li>индексация документов и RAG-запросы тоже не пройдут;</li>
          <li>
            так сделано намеренно — платный вызов не уходит, если расход нельзя
            учесть в бюджете.
          </li>
        </ul>
        {onSetupPrice && (
          <div className="mt-2">
            <Button size="sm" onClick={onSetupPrice}>
              Настроить цену
            </Button>
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}
