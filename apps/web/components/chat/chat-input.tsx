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
// поддержанные возможности. Режим обработки данных показывается лишь когда
// сервер подтвердил готовность (capabilities.protection.enabled).
import { useId, useState } from "react";
import { Brain, Globe, Paperclip, Send, Shield, Square } from "lucide-react";

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
  /** Веб-поиск запрещён текущим режимом: тумблер остаётся, но неактивен. */
  webSearchBlocked?: boolean;
  /** Доступны ли защищённые режимы (сервер подтвердил готовность). */
  protectionAvailable?: boolean;
  /** Текущий режим обработки данных диалога. */
  protectionMode?: string;
  /** Смена режима обработки данных. */
  onProtectionModeChange?: (mode: string) => void;
  /** Идёт смена режима или подготовка — переключатель блокируется. */
  protectionBusy?: boolean;
}

/** Режимы обработки данных (ADR-0007). Подписи короткие: все элементы
 *  управления должны умещаться в одну строку, поэтому полное название и
 *  объяснение показываются внутри выпадающего меню. */
const PROTECTION_MODES = [
  {
    value: "cloud_controlled",
    label: "Облако",
    fullLabel: "Облако с предупреждениями",
    hint: "Исходный текст уходит выбранной модели. Перед отправкой показываем, какие данные найдены.",
  },
  {
    value: "protected_hybrid",
    label: "Гибрид",
    fullLabel: "Защищённый гибрид",
    hint: "Наружу уходит только очищенный текст с псевдонимами; ответ восстанавливается локально.",
  },
  {
    value: "local_only",
    label: "Локально",
    fullLabel: "Только локально",
    hint: "Данные уходят только провайдеру, помеченному локальным; веб-поиск запрещён. Нужен запущенный Ollama/LM Studio.",
  },
] as const;

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
  webSearchBlocked = false,
  protectionAvailable = false,
  protectionMode = "cloud_controlled",
  onProtectionModeChange,
  protectionBusy = false,
}: ChatInputProps) {
  const [reasoningDepth, setReasoningDepth] =
    useState<ReasoningDepth>("medium");
  const [modeOpen, setModeOpen] = useState(false);
  const textareaId = useId();
  const webSearchId = useId();
  const selected = models.find((m) => m.id === selectedModel);
  const currentMode =
    PROTECTION_MODES.find((mode) => mode.value === protectionMode) ??
    PROTECTION_MODES[0];
  // Без цены backend блокирует платный вызов, поэтому предупреждение не
  // скрывается пользователем: это не подсказка, а объяснение отказа.
  const showPricingWarning = Boolean(selected && !selected.hasPrice);
  // Без моделей отправлять нечего: поле ввода остаётся на месте (чтобы
  // раскладка не «прыгала» и пользователь видел, куда вернуться), но
  // блокируется с понятной подсказкой.
  const noModels = models.length === 0;
  const canSend = value.trim().length > 0 && !isStreaming && !noModels;

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
    <div className="bg-background/95 supports-[backdrop-filter]:bg-background/80 m-2 mt-0 rounded-xl border shadow-[0_10px_28px_-10px_rgba(15,23,42,0.35)] backdrop-blur lg:m-3 lg:mt-0 lg:rounded-2xl">
      <div className="w-full space-y-3 p-3 lg:p-4">
        {showPricingWarning && selected && (
          <ModelPricingWarning
            modelName={selected.name}
            onSetupPrice={onSetupPrice}
          />
        )}

        {/* Одна строка на всю ширину: модель, глубина рассуждений, режим
            обработки данных и веб-доступ. На узких экранах строка
            прокручивается по горизонтали, а не превращается в три этажа. */}
        <div className="flex items-center gap-2 overflow-x-auto">
          <div className="min-w-0 flex-1">
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
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  aria-label={`Глубина рассуждений: ${currentLevel?.label ?? "Средняя"}`}
                >
                  <Brain />
                  {currentLevel?.label ?? "Средняя"}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80 shadow-lg">
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

          {/* Режим обработки данных: выпадающее меню, как у глубины
              рассуждений. Полные названия и подсказки — внутри меню, чтобы
              строка оставалась однострочной. */}
          {protectionAvailable && onProtectionModeChange && (
            <Popover open={modeOpen} onOpenChange={setModeOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  disabled={protectionBusy}
                  aria-label={`Режим обработки данных: ${currentMode.label}`}
                  title="Облако, защищённый гибрид или только локально"
                >
                  <Shield />
                  {currentMode.label}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80 shadow-lg" align="start">
                <div className="space-y-3">
                  <div>
                    <h4 className="text-pah-base font-medium">
                      Режим обработки данных
                    </h4>
                    <p className="text-muted-foreground text-pah-sm">
                      Выбирайте по чувствительности текста. Режим хранится в
                      диалоге; в гибриде отправка требует подтверждения.
                    </p>
                  </div>
                  <Separator />
                  <div
                    role="radiogroup"
                    aria-label="Режим обработки данных"
                    className="space-y-1"
                  >
                    {PROTECTION_MODES.map((mode) => (
                      <button
                        key={mode.value}
                        type="button"
                        role="radio"
                        aria-checked={currentMode.value === mode.value}
                        onClick={() => {
                          onProtectionModeChange(mode.value);
                          setModeOpen(false);
                        }}
                        className={cn(
                          "w-full rounded-md border p-3 text-left transition-colors",
                          currentMode.value === mode.value
                            ? "border-primary bg-primary/5"
                            : "hover:bg-accent border-transparent",
                        )}
                      >
                        <div className="text-pah-base font-medium">
                          {mode.fullLabel}
                        </div>
                        <div className="text-muted-foreground text-pah-sm">
                          {mode.hint}
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
            <div className="flex shrink-0 items-center gap-2">
              <Switch
                id={webSearchId}
                checked={webSearchBlocked ? false : webSearch}
                onCheckedChange={onWebSearchChange}
                disabled={webSearchBlocked}
              />
              <Label
                htmlFor={webSearchId}
                className={cn(
                  "gap-1 whitespace-nowrap",
                  webSearchBlocked
                    ? "text-muted-foreground cursor-not-allowed"
                    : "cursor-pointer",
                )}
                title={
                  webSearchBlocked
                    ? "В локальном режиме веб-поиск запрещён: это внешний запрос"
                    : "Ответ будет обоснован результатами веб-поиска; найденные страницы попадут во вход запроса"
                }
              >
                <Globe className="size-4" aria-hidden="true" />
                Веб
              </Label>
            </div>
          )}

          {remainingBudget?.daily && (
            <p className="text-muted-foreground ml-auto shrink-0 text-pah-sm whitespace-nowrap">
              Осталось сегодня: {remainingBudget.daily}{" "}
              {remainingBudget.currency}
            </p>
          )}
        </div>

        <div className="relative">
          {/* Метка визуально скрыта, но обязана быть уникальной: имя
              «Сообщение» совпадало с placeholder'ом «Напишите сообщение…»,
              из-за чего поиск по доступному имени находил два элемента. */}
          <Label htmlFor={textareaId} className="sr-only">
            Текст сообщения
          </Label>
          <Textarea
            id={textareaId}
            value={value}
            onChange={(e) => onValueChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              noModels
                ? "Сначала добавьте провайдера и синхронизируйте модели"
                : "Напишите сообщение… (Enter — отправить, Shift+Enter — новая строка)"
            }
            className="min-h-20 pr-24"
            disabled={isStreaming || noModels}
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
