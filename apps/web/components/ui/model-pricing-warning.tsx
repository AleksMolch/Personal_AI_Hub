// Предупреждение о модели без настроенной цены.
//
// Назначение: честно объяснить последствия, но НЕ блокировать работу. Цена
// необязательна (ADR-0008): без неё генерация разрешена, стоимость пишется как
// `unknown`, а денежный лимит не резервируется и не гарантируется.
//
// Место в архитектуре: представление состояния конфигурации; используется в
// чате при выборе модели и на странице моделей.
import { Info } from "lucide-react";

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
 * Информационное предупреждение «цена не настроена».
 *
 * @param props Имя модели и обработчик перехода к настройке цены.
 * @returns Блок Alert с объяснением последствий и кнопкой настройки.
 */
export function ModelPricingWarning({
  modelName,
  onSetupPrice,
  className,
}: ModelPricingWarningProps) {
  return (
    <Alert className={cn("border-warning/50", className)}>
      <Info />
      <AlertTitle>Цена не задана — стоимость будет неизвестна</AlertTitle>
      <AlertDescription className="mt-1 space-y-2">
        <p>
          Модель <strong>{modelName}</strong> работает без цены. Отправлять
          сообщения можно, но расход по таким запросам не считается и не
          ограничивается бюджетом.
        </p>
        <ul className="text-muted-foreground list-inside list-disc space-y-0.5 text-sm">
          <li>стоимость ответа показывается как unknown;</li>
          <li>денежный лимит не резервируется под такие запросы;</li>
          <li>
            индексация и RAG используют embedding-модель: для неё цена нужна
            отдельно.
          </li>
        </ul>
        {onSetupPrice && (
          <div className="mt-2">
            <Button size="sm" variant="outline" onClick={onSetupPrice}>
              Настроить цену
            </Button>
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}
