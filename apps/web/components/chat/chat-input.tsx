"use client";

// Форма ввода сообщения в чате.
//
// Назначение: собрать параметры запроса перед отправкой — модель, глубину
// рассуждений, дополнительные режимы — и передать текст в родительский
// компонент. Показывает предупреждение, если у выбранной модели не задана цена,
// и остаток дневного бюджета.
//
// Место в архитектуре: презентационный компонент; сам ничего не отправляет и
// не знает про API. Родитель (страница чата) решает, что делать с параметрами.
//
// Принципиальное ограничение: элементы управления отражают ТОЛЬКО реально
// поддержанные возможности. «Веб-доступ» и «Локально» здесь отсутствуют
// намеренно — backend их пока не реализует, а показывать неработающий тумблер
// запрещено правилами проекта.
import { useId, useState } from "react";
import { Brain, Globe, Paperclip, Send, ShieldOff, Square } from "lucide-react";

import { ModelPricingWarning } from "@/components/ui/model-pricing-warning";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** Глубина рассуждений модели. Значения совпадают с литералами backend. */
export type ReasoningDepth = "low" | "medium" | "high";

/** Описание уровня глубины для интерфейса. */
const REASONING_LEVELS: {
  value: ReasoningDepth;
  label: string;
  hint: string;
}[] = [
  {
    value: "low",
    label: "Низкая",
    hint: "Быстрые ответы, минимальная стоимость",
  },
  { value: "medium", label: "Средняя", hint: "Баланс качества и стоимости" },
  {
    value: "high",
    label: "Высокая",
    hint: "Глубокий анализ, выше стоимость и задержка",
  },
];

/** Модель в том виде, как её видит форма ввода. */
export interface ChatInputModel {
  /** Идентификатор профиля модели. */
  id: string;
  /** Отображаемое имя. */
  name: string;
  /** Задана ли цена (PriceSnapshot). */
  hasPrice: boolean;
  /** Поддерживает ли модель управление глубиной рассуждений. */
  supportsReasoning: boolean;
}

interface ChatInputProps {
  /** Доступные модели. */
  models: ChatInputModel[];
  /** Выбранная модель. */
  selectedModel: string;
  /** Смена модели. */
  onModelChange: (modelId: string) => void;
  /** Отправка сообщения с выбранными параметрами. */
  onSend: (
    message: string,
    options: { reasoningDepth?: ReasoningDepth },
  ) => void; /** Остановить текущую генерацию. */
  onStop?: () => void;
  /** Идёт ли потоковый ответ. */
  isStreaming?: boolean;
  /** Остаток дневного бюджета для подсказки. */
  remainingBudget?: { daily: string | null; currency: string };
  /** Переход к настройке цены выбранной модели. */
  onSetupPrice?: () => void;
  /** Текст в поле ввода (контролируемое значение — нужно для примеров). */
  value: string;
  /** Изменение текста в поле ввода. */
  onValueChange: (value: string) => void;
  /** Включён ли на сервере веб-поиск (иначе переключатель не показываем). */
  webSearchAvailable?: boolean;
  /** Выбран ли веб-поиск для следующего сообщения. */
  webSearch?: boolean;
  /** Изменение режима веб-поиска. */
  onWebSearchChange?: (enabled: boolean) => void;
}

/**
 * Форма ввода сообщения с селекторами модели и глубины рассуждений.
 *
 * @param props Модели, выбранное значение, обработчики и состояние стрима.
 * @returns Панель ввода с предупреждениями и кнопками отправки/остановки.
 */
export function ChatInput({
  models,
  selectedModel,
  onModelChange,
  onSend,
  onStop,
  isStreaming = false,
  remainingBudget,
  onSetupPrice,
  value,
  onValueChange,
  webSearchAvailable = false,
  webSearch = false,
  onWebSearchChange,
}: ChatInputProps) {
  const [reasoningDepth, setReasoningDepth] =
    useState<ReasoningDepth>("medium");
  const textareaId = useId();
  const localModeId = useId();
  const webSearchId = useId();

  const selected = models.find((m) => m.id === selectedModel);
  // Без цены backend блокирует платный вызов, поэтому предупреждение не
  // скрывается пользователем: это не подсказка, а объяснение отказа.
  const showPricingWarning = Boolean(selected && !selected.hasPrice);
  const canSend = value.trim().length > 0 && !isStreaming;

  /** Отправляет сообщение и очищает поле ввода. */
  function submit() {
    if (!canSend) return;
    onSend(value, {
      // Глубину передаём только для моделей, которые её поддерживают,
      // иначе backend справедливо отклонит параметр.
      reasoningDepth: selected?.supportsReasoning ? reasoningDepth : undefined,
    });
    onValueChange("");
  }

  /** Enter отправляет, Shift+Enter добавляет строку. */
  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  const currentLevel = REASONING_LEVELS.find((l) => l.value === reasoningDepth);

  return (
    <div className="bg-background/95 supports-[backdrop-filter]:bg-background/75 border-t backdrop-blur">
      <div className="mx-auto max-w-3xl space-y-3 p-4">
        {showPricingWarning && selected && (
          <ModelPricingWarning
            modelName={selected.name}
            onSetupPrice={onSetupPrice}
          />
        )}

        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-[200px] flex-1">
            <Label htmlFor="chat-model" className="sr-only">
              Модель
            </Label>
            <Select value={selectedModel} onValueChange={onModelChange}>
              <SelectTrigger id="chat-model" aria-label="Модель">
                <SelectValue placeholder="Выберите модель" />
              </SelectTrigger>
              <SelectContent>
                {models.map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    <span className="flex items-center gap-2">
                      {model.name}
                      {!model.hasPrice && (
                        <Badge variant="outline" className="text-pah-xs">
                          Без цены
                        </Badge>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Селектор глубины показываем только там, где модель это умеет:
              иначе тумблер был бы декоративным. */}
          {selected?.supportsReasoning && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm">
                  <Brain />
                  Глубина: {currentLevel?.label ?? "Средняя"}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80">
                <div className="space-y-3">
                  <div>
                    <h4 className="text-pah-base font-medium">
                      Глубина рассуждений
                    </h4>
                    <p className="text-muted-foreground text-pah-sm">
                      Влияет на качество ответа, задержку и стоимость: токены
                      рассуждений тарифицируются как выходные.
                    </p>
                  </div>
                  <Separator />
                  <div
                    role="radiogroup"
                    aria-label="Глубина рассуждений"
                    className="space-y-1"
                  >
                    {REASONING_LEVELS.map((level) => (
                      <button
                        key={level.value}
                        type="button"
                        role="radio"
                        aria-checked={reasoningDepth === level.value}
                        onClick={() => setReasoningDepth(level.value)}
                        className={cn(
                          "w-full rounded-md border p-3 text-left transition-colors",
                          reasoningDepth === level.value
                            ? "border-primary bg-primary/5"
                            : "hover:bg-accent border-transparent",
                        )}
                      >
                        <div className="text-pah-base font-medium">
                          {level.label}
                        </div>
                        <div className="text-muted-foreground text-pah-sm">
                          {level.hint}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          )}

          {/* Веб-доступ: показываем только если поиск включён на сервере.
              Один запрос — максимум один поиск, поэтому это не «агент», а
              разовое обоснование ответа источниками. */}
          {webSearchAvailable && (
            <div className="flex items-center gap-2">
              <Switch
                id={webSearchId}
                checked={webSearch}
                onCheckedChange={onWebSearchChange}
              />
              <Label
                htmlFor={webSearchId}
                className="cursor-pointer gap-1"
                title="Ответ будет обоснован результатами веб-поиска; найденные страницы попадут во вход запроса"
              >
                <Globe className="size-4" aria-hidden="true" />
                Веб
              </Label>
            </div>
          )}

          {/* Заглушка локального режима: честно сообщаем, что он появится на
              Этапе 2, вместо неработающего переключателя. */}
          <div className="flex items-center gap-2">
            <Switch id={localModeId} disabled checked={false} />
            <Label
              htmlFor={localModeId}
              className="text-muted-foreground cursor-not-allowed gap-1"
              title="Локальный inference появится на Этапе 2: сейчас все запросы идут во внешний API-провайдер"
            >
              <ShieldOff className="size-4" aria-hidden="true" />
              Локально
              <span className="text-pah-xs">(скоро)</span>
            </Label>
          </div>

          {remainingBudget?.daily && (
            <p className="text-muted-foreground ml-auto text-pah-sm">
              Осталось сегодня: {remainingBudget.daily}{" "}
              {remainingBudget.currency}
            </p>
          )}
        </div>

        <div className="relative">
          <Label htmlFor={textareaId} className="sr-only">
            Сообщение
          </Label>
          <Textarea
            id={textareaId}
            value={value}
            onChange={(e) => onValueChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Напишите сообщение… (Enter — отправить, Shift+Enter — новая строка)"
            className="min-h-20 pr-24"
            disabled={isStreaming}
          />
          <div className="absolute right-2 bottom-2 flex gap-1">
            {/* Прикрепление файлов появится вместе с передачей вложений в чат;
                кнопка не показывается, пока этого нет в API. */}
            <Button
              type="button"
              size="icon"
              variant="ghost"
              disabled
              aria-label="Прикрепить файл (пока недоступно)"
              title="Прикрепление файлов к сообщению пока не поддерживается"
            >
              <Paperclip />
            </Button>
            {isStreaming ? (
              <Button
                type="button"
                size="icon"
                variant="destructive"
                onClick={onStop}
                aria-label="Остановить генерацию"
              >
                <Square />
              </Button>
            ) : (
              <Button
                type="button"
                size="icon"
                onClick={submit}
                disabled={!canSend}
                aria-label="Отправить сообщение"
              >
                <Send />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
