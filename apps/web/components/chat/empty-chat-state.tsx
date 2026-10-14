"use client";

// Пустое состояние чата.
//
// Назначение: когда диалог пуст, показать пользователю, что делать дальше, и
// дать готовые примеры запросов — это снижает порог входа и объясняет
// возможности продукта (документы, таблицы, база знаний).
//
// Место в архитектуре: презентационный компонент чата; примеры передаются
// снаружи, чтобы не дублировать продуктовые сценарии в вёрстке.
import { MessageSquarePlus, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface EmptyChatStateProps {
  /** Создать новый диалог. */
  onNewChat?: () => void;
  /** Подставить пример в поле ввода. */
  onUseExample?: (text: string) => void;
  /** Примеры запросов; если не заданы — блок примеров не показывается. */
  examples?: string[];
}

/**
 * Приглашение к первому запросу.
 *
 * @param props Обработчики и список примеров.
 * @returns Центрированный блок с иконкой, пояснением и примерами.
 */
export function EmptyChatState({
  onNewChat,
  onUseExample,
  examples = [],
}: EmptyChatStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 p-8 text-center">
      <div className="bg-primary/10 flex size-14 items-center justify-center rounded-full">
        <Sparkles className="text-primary size-7" aria-hidden="true" />
      </div>

      <div>
        <h2 className="text-pah-xl font-semibold">Начните диалог</h2>
        <p className="text-muted-foreground mx-auto mt-2 max-w-md text-pah-sm">
          Задайте вопрос или выберите пример ниже. Стоимость каждого ответа
          видна под сообщением, а дневной лимит проверяется до отправки запроса.
        </p>
      </div>

      {examples.length > 0 && onUseExample && (
        <div className="grid w-full max-w-xl gap-2">
          {examples.map((example) => (
            <Card
              key={example}
              className="hover:bg-accent cursor-pointer p-3 text-left transition-colors"
              onClick={() => onUseExample(example)}
            >
              <p className="text-pah-sm">{example}</p>
            </Card>
          ))}
        </div>
      )}

      {onNewChat && (
        <Button onClick={onNewChat}>
          <MessageSquarePlus />
          Новый диалог
        </Button>
      )}
    </div>
  );
}
