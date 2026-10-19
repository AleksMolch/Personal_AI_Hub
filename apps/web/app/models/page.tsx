"use client";

// Страница «Модели и цены»: просмотр синхронизированных моделей провайдеров и
// задание цены за 1M токенов (вход/выход).
//
// Назначение: это единственное место, где пользователь задаёт цену модели.
// Пока цена не задана, чат с моделью заблокирован, поэтому страница определяет,
// какие модели вообще доступны в разделе «Чат», и наполняет экономический учёт.
// Место в архитектуре: клиентская страница Next.js (App Router). Обращается
// только к собственному backend через типизированный клиент `@/lib/api`
// (GET /api/v1/models, GET /api/v1/prices, POST /api/v1/prices); напрямую к
// внешним AI-провайдерам UI не ходит. Общую шапку и навигацию даёт AppShell,
// визуальные примитивы — компоненты из `@/components/ui`.
// Основные сущности файла: ModelsPage (загрузка данных и сохранение цены),
// ModelPriceCard (форма цены одной модели), ModelsSkeleton (заглушка загрузки).

import { FormEvent, useCallback, useEffect, useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { TriangleAlert } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  api,
  getToken,
  isValidDecimal,
  ModelProfile,
  normalizeDecimalInput,
  Price,
  type PriceImportResult,
  setToken,
} from "@/lib/api";

/** Текст пустого состояния: формулировка должна совпадать дословно. */
const EMPTY_MODELS_TEXT =
  "Моделей нет. Сначала добавьте провайдера и синхронизируйте модели на странице «Провайдеры».";

/** Пояснение для модели без цены: без цены чат с моделью заблокирован. */
const MISSING_PRICE_TEXT = "Цена не задана — чат с этой моделью заблокирован.";

// Классы состояния цены заданы готовыми строками в справочнике: Tailwind
// собирает классы статически и интерполяцию вида `text-${state}` не увидит.
const PRICE_TEXT_CLASS = {
  set: "text-pah-sm text-foreground",
  missing: "text-pah-sm text-cost-unknown",
} as const;

/**
 * Форматирует цену, убирая хвостовые нули.
 *
 * Backend хранит деньги как `NUMERIC(20,8)` и отдаёт Decimal строкой
 * («0.02200000»). Показывать восемь знаков после запятой бессмысленно — это
 * шум, который мешает прочитать цену. Работаем со строкой, а не с числом,
 * чтобы не потерять точность на пути к отображению.
 *
 * @param value Денежное значение в виде Decimal-строки.
 * @returns Строка без хвостовых нулей: «0.022», «1.98», «10».
 */
function formatPrice(value: string): string {
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" ? "0" : trimmed;
}

/** Ключи для трёх карточек-заглушек (фиксированные, без индексов массива). */
const SKELETON_KEYS = ["first", "second", "third"] as const;

/** Человекочитаемые названия полей цены для результата импорта. */
const IMPORT_FIELD_LABELS: Record<string, string> = {
  input_per_million: "Вход (cache miss)",
  output_per_million: "Выход",
  cache_read_per_million: "Cache hit",
  cache_write_per_million: "Cache write",
};

interface ModelPriceCardProps {
  /** Модель из каталога backend. */
  model: ModelProfile;
  /** Действующая цена модели или null, если цена ещё не задана. */
  price: Price | null;
  /** Текущее значение поля «цена входа». */
  inputValue: string;
  /** Текущее значение поля «цена выхода». */
  outputValue: string;
  /** Текущее значение поля «цена попадания в кэш». */
  cacheReadValue: string;
  /** Текущее значение поля «цена записи в кэш». */
  cacheWriteValue: string;
  /** Объявлена ли у модели возможность управления глубиной рассуждений. */
  supportsReasoning: boolean;
  /** Идёт ли сохранение объявленных возможностей. */
  reasoningBusy: boolean;
  /** Признак того, что цена этой модели только что сохранена. */
  justSaved: boolean;
  /** Изменение поля «цена входа». */
  onInputChange: (value: string) => void;
  /** Изменение поля «цена выхода». */
  onOutputChange: (value: string) => void;
  /** Изменение поля «цена попадания в кэш». */
  onCacheReadChange: (value: string) => void;
  /** Изменение поля «цена записи в кэш». */
  onCacheWriteChange: (value: string) => void;
  /** Переключение поддержки глубины рассуждений. */
  onReasoningChange: (enabled: boolean) => void;
  /** Отправка формы сохранения цены. */
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

/**
 * Карточка одной модели: действующая цена и форма её сохранения.
 *
 * @param props Модель, действующая цена, значения полей и обработчики.
 * @returns Карточку с подписанными полями ввода и кнопкой «Сохранить».
 */
function ModelPriceCard({
  model,
  price,
  inputValue,
  outputValue,
  cacheReadValue,
  cacheWriteValue,
  supportsReasoning,
  reasoningBusy,
  justSaved,
  onInputChange,
  onOutputChange,
  onCacheReadChange,
  onCacheWriteChange,
  onReasoningChange,
  onSubmit,
}: ModelPriceCardProps) {
  // useId даёт уникальные id для пар label/input: карточек на странице много,
  // а id в документе должны быть уникальны, иначе label свяжется не с тем полем.
  const fieldId = useId();
  const inputId = `${fieldId}-input`;
  const outputId = `${fieldId}-output`;
  const cacheReadId = `${fieldId}-cache-read`;
  const cacheWriteId = `${fieldId}-cache-write`;
  const reasoningId = `${fieldId}-reasoning`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{model.display_name}</CardTitle>
        <CardDescription className="font-mono break-all">
          {model.external_model_id}
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <p
            className={price ? PRICE_TEXT_CLASS.set : PRICE_TEXT_CLASS.missing}
          >
            {price
              ? `Текущая цена: $${formatPrice(price.input_per_million)} / $${formatPrice(price.output_per_million)} за 1M токенов (вход/выход)`
              : MISSING_PRICE_TEXT}
          </p>
          {price?.cache_read_per_million && (
            <p className="text-pah-sm text-muted-foreground">
              Кэш (попадание): ${formatPrice(price.cache_read_per_million)} за
              1M токенов — вход по этой цене оплачивается дешевле.
            </p>
          )}
          {price?.cache_write_per_million && (
            <p className="text-pah-sm text-muted-foreground">
              Кэш (запись): ${formatPrice(price.cache_write_per_million)} за 1M
              токенов.
            </p>
          )}
        </div>

        {/* Форма не имеет видимой подписи, поэтому имя задано через aria-label. */}
        <form
          onSubmit={onSubmit}
          aria-label={`Цена модели ${model.display_name}`}
          className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex w-full flex-col gap-1.5 sm:w-40">
            <Label htmlFor={inputId}>Цена входа (cache miss), $/1M</Label>
            <Input
              id={inputId}
              value={inputValue}
              onChange={(event) => onInputChange(event.target.value)}
              placeholder={price?.input_per_million ?? "0.15"}
              inputMode="decimal"
              autoComplete="off"
            />
          </div>

          <div className="flex w-full flex-col gap-1.5 sm:w-40">
            <Label htmlFor={cacheReadId}>Цена cache hit, $/1M</Label>
            <Input
              id={cacheReadId}
              value={cacheReadValue}
              onChange={(event) => onCacheReadChange(event.target.value)}
              placeholder={price?.cache_read_per_million ?? "необязательно"}
              inputMode="decimal"
              autoComplete="off"
            />
          </div>

          <div className="flex w-full flex-col gap-1.5 sm:w-40">
            <Label htmlFor={outputId}>Цена выхода, $/1M</Label>
            <Input
              id={outputId}
              value={outputValue}
              onChange={(event) => onOutputChange(event.target.value)}
              placeholder={price?.output_per_million ?? "0.60"}
              inputMode="decimal"
              autoComplete="off"
            />
          </div>

          <div className="flex w-full flex-col gap-1.5 sm:w-40">
            <Label htmlFor={cacheWriteId}>Цена cache write, $/1M</Label>
            <Input
              id={cacheWriteId}
              value={cacheWriteValue}
              onChange={(event) => onCacheWriteChange(event.target.value)}
              placeholder={price?.cache_write_per_million ?? "необязательно"}
              inputMode="decimal"
              autoComplete="off"
            />
          </div>

          <Button type="submit" className="w-full sm:w-auto">
            Сохранить
          </Button>
        </form>

        <p className="text-pah-xs text-muted-foreground">
          Цена входа — это стоимость промаха кэша (cache miss). Если у модели
          есть отдельный тариф попадания в кэш (cache hit), укажите его: иначе
          кэшированные токены будут считаться по цене входа, и расчёт разойдётся
          со счётом провайдера. Оба поля принимают запятую и точку.
        </p>

        {/* Возможности модели объявляются вручную: провайдеры не всегда их
            рекламируют (DeepSeek принимает reasoning_effort, но в /models этого
            не сообщает). Без переключателя селектор глубины в чате оставался бы
            скрытым, хотя модель параметр поддерживает. */}
        <div className="flex items-start gap-3 rounded-md border p-3">
          <Switch
            id={reasoningId}
            checked={supportsReasoning}
            onCheckedChange={onReasoningChange}
            disabled={reasoningBusy}
          />
          <div className="flex flex-col gap-1">
            <Label htmlFor={reasoningId} className="cursor-pointer">
              Модель поддерживает глубину рассуждений
            </Label>
            <p className="text-pah-xs text-muted-foreground">
              Включает селектор «Глубина» в чате: low / medium / high уходят
              провайдеру как `reasoning_effort` (OpenRouter — как
              `reasoning.effort`). Включайте только если модель это принимает —
              сверьтесь с документацией провайдера.
            </p>
          </div>
        </div>

        {justSaved && (
          <p role="status" className="text-pah-sm text-cost-low">
            Цена сохранена.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Заглушка на время первой загрузки: повторяет структуру карточек моделей,
 * чтобы интерфейс не «прыгал» после прихода данных.
 *
 * @returns Три карточки-скелета; сами скелеты скрыты от скринридеров, о факте
 *   загрузки сообщает отдельный текст в live-регионе.
 */
function ModelsSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="sr-only">
        Загрузка моделей…
      </p>
      {SKELETON_KEYS.map((key) => (
        <Card key={key}>
          <CardHeader>
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-3 w-1/3" />
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Skeleton className="h-9 w-full sm:w-40" />
            <Skeleton className="h-9 w-full sm:w-40" />
            <Skeleton className="h-9 w-full sm:w-28" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/**
 * Страница «Модели и цены».
 *
 * @returns Разметку страницы в AppShell: состояние ошибки, скелет первой
 *   загрузки, пустое состояние или список карточек моделей с формами цены.
 */
export default function ModelsPage() {
  const router = useRouter();
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [prices, setPrices] = useState<Record<string, Price | null>>({});
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  // Отдельные тарифы кэша: у DeepSeek, Anthropic и других вход делится на
  // cache miss (обычная цена входа) и cache hit (дешевле), плюс бывает
  // запись в кэш. Без этих полей стоимость ответа считалась бы по одной цене
  // и расходилась со счётом провайдера.
  const [cacheReads, setCacheReads] = useState<Record<string, string>>({});
  const [cacheWrites, setCacheWrites] = useState<Record<string, string>>({});
  /** Идёт ли сохранение возможностей по конкретной модели. */
  const [reasoningBusy, setReasoningBusy] = useState<Record<string, boolean>>(
    {},
  );
  /** Адрес страницы тарифов для разбора. */
  const [importUrl, setImportUrl] = useState("");
  /** Найденные кандидаты (null — разбор ещё не запускали). */
  const [importResult, setImportResult] = useState<PriceImportResult | null>(
    null,
  );
  /** Идёт ли загрузка и разбор страницы. */
  const [importBusy, setImportBusy] = useState(false);
  /** Модель, к которой применяются найденные значения. */
  const [importModelId, setImportModelId] = useState("");
  const importUrlId = useId();
  const importModelSelectId = useId();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  // Флаг взводится только на первую загрузку и больше не сбрасывается: при
  // перезагрузке после сохранения список уже отрисован, и скелет (а вместе с
  // ним и пустое состояние) не должен мелькать поверх готовых данных.
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const ms = await api.models();
      setModels(ms);
      // Цены запрашиваются по одной модели: backend отдаёт их только в разрезе
      // профиля модели, отдельного «списка всех цен» в API нет.
      const priceMap: Record<string, Price | null> = {};
      for (const m of ms) {
        try {
          const list = await api.prices(m.id);
          // Действующая цена — самая свежая запись (backend сортирует список).
          priceMap[m.id] = list.length > 0 ? list[0] : null;
        } catch {
          // Ошибка по одной модели не должна ломать показ остальных: считаем,
          // что цена не задана, и оставляем чат с этой моделью заблокированным.
          priceMap[m.id] = null;
        }
      }
      setPrices(priceMap);
    } catch (err) {
      if (
        err instanceof Error &&
        "status" in err &&
        (err as { status: number }).status === 401
      ) {
        // Токен истёк: очищаем его и уводим на вход, иначе пользователь
        // останется на странице с пустым списком моделей.
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка загрузки.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch на mount
    void load();
  }, [load, router]);

  /**
   * Объявляет или снимает у модели поддержку глубины рассуждений.
   *
   * Провайдер не всегда сообщает о поддержке параметра, поэтому возможность
   * объявляется данными: capability `reasoning` включает селектор в чате.
   *
   * @param model Модель, для которой меняется набор возможностей.
   * @param enabled Новое состояние переключателя.
   * @returns Промис без значения. Побочные эффекты: PATCH /api/v1/models/{id}
   *   и обновление списка.
   */
  async function onReasoningChange(model: ModelProfile, enabled: boolean) {
    setError(null);
    setReasoningBusy((s) => ({ ...s, [model.id]: true }));
    try {
      // Отправляем только возможности, которыми управляет пользователь:
      // `chat` и `streaming` выставляет синхронизация, и backend их сохраняет
      // сам. Если передать их в PATCH, валидатор отклонит запрос как
      // неизвестные значения.
      const managed = ["tools", "vision", "structured_output"];
      const current = model.capabilities.filter((cap) => managed.includes(cap));
      const next = enabled ? [...current, "reasoning"] : current;
      await api.updateModelCapabilities(model.id, next);
      await load();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось изменить возможности модели.",
      );
    } finally {
      setReasoningBusy((s) => ({ ...s, [model.id]: false }));
    }
  }

  /**
   * Сохраняет цену модели в валюте USD.
   *
   * @param e Событие отправки формы (отменяет перезагрузку страницы).
   * @param model Модель, для которой сохраняется цена.
   * @returns Промис без значения. Побочные эффекты: POST /api/v1/prices,
   *   повторная загрузка цен и сообщение об успехе или ошибке.
   */
  async function onSave(e: FormEvent, model: ModelProfile) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    // Принимаем и запятую (`0,022`), и точку (`0.022`): русская локаль
    // использует запятую, и без нормализации запрос падал с 422.
    const input = normalizeDecimalInput(inputs[model.id] ?? "");
    const output = normalizeDecimalInput(outputs[model.id] ?? "");
    const cacheRead = normalizeDecimalInput(cacheReads[model.id] ?? "");
    const cacheWrite = normalizeDecimalInput(cacheWrites[model.id] ?? "");
    if (!input || !output) {
      setError("Укажите цену входа и выхода.");
      return;
    }
    const values = [input, output, cacheRead, cacheWrite].filter(Boolean);
    if (!values.every(isValidDecimal)) {
      setError(
        "Цена должна быть неотрицательным числом, например 0.022 или 0,022.",
      );
      return;
    }
    try {
      await api.createPrice({
        model_profile_id: model.id,
        input_per_million: input,
        output_per_million: output,
        // Пустое поле = тариф не задан. Тогда вход считается по цене входа,
        // то есть скидки за кэш не будет — лучше, чем выдуманная цена.
        cache_read_per_million: cacheRead || null,
        cache_write_per_million: cacheWrite || null,
        currency: "USD",
      });
      setSaved(model.id);
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось сохранить цену.",
      );
    }
  }

  /** Действующая цена модели или null, если цена не задана. */
  function currentPrice(modelId: string): Price | null {
    return prices[modelId] ?? null;
  }

  /**
   * Загружает страницу тарифов провайдера и показывает найденные значения.
   *
   * Ничего не сохраняет: провайдеры не дают машинно-читаемого контракта на
   * страницу тарифов, поэтому найденное — подсказка, которую обязан проверить
   * пользователь.
   *
   * @returns Промис без значения. Побочные эффекты: POST /prices/extract.
   */
  async function onExtract() {
    setError(null);
    setImportResult(null);
    if (!importUrl.trim()) {
      setError("Укажите адрес страницы с тарифами провайдера.");
      return;
    }
    setImportBusy(true);
    try {
      setImportResult(await api.extractPrices(importUrl.trim()));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось разобрать страницу тарифов.",
      );
    } finally {
      setImportBusy(false);
    }
  }

  /**
   * Подставляет КОНКРЕТНОГО кандидата в поле выбранной модели.
   *
   * На странице тарифов обычно несколько моделей, поэтому значения идут парой
   * (например, Flash и Pro). Брать первое найденное автоматически нельзя —
   * легко подставить цену чужой модели. Пользователь выбирает нужную строку.
   *
   * Сохранение НЕ выполняется: после подстановки нужно проверить числа и
   * нажать «Сохранить» в карточке модели.
   *
   * @param field Поле цены.
   * @param value Значение цены из найденного кандидата.
   */
  function applyCandidate(field: string, value: string) {
    if (!importModelId) return;
    const id = importModelId;
    if (field === "input_per_million") {
      setInputs((s) => ({ ...s, [id]: value }));
    } else if (field === "output_per_million") {
      setOutputs((s) => ({ ...s, [id]: value }));
    } else if (field === "cache_read_per_million") {
      setCacheReads((s) => ({ ...s, [id]: value }));
    } else if (field === "cache_write_per_million") {
      setCacheWrites((s) => ({ ...s, [id]: value }));
    }
  }

  return (
    <AppShell
      title="Модели и цены"
      description="Просмотр доступных моделей и настройка цены за миллион токенов."
    >
      {error && (
        <Alert variant="destructive" role="alert">
          <TriangleAlert />
          <AlertTitle>Ошибка</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading && <ModelsSkeleton />}

      {!loading && models.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Список моделей пуст</CardTitle>
            <CardDescription>{EMPTY_MODELS_TEXT}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link href="/providers">Перейти к провайдерам</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {!loading && models.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Подставить цены со страницы тарифов</CardTitle>
            <CardDescription>
              Вставьте адрес страницы с ценами провайдера. Платформа попробует
              найти значения и покажет фрагменты, но{" "}
              <strong>не сохранит их</strong>: проверьте числа сами и
              подтвердите — страницы тарифов меняются, а ошибка в цене искажает
              учёт расходов.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="flex-1">
                <Label htmlFor={importUrlId} className="sr-only">
                  Адрес страницы тарифов
                </Label>
                <Input
                  id={importUrlId}
                  value={importUrl}
                  onChange={(event) => setImportUrl(event.target.value)}
                  placeholder="https://api-docs.deepseek.com/quick_start/pricing"
                  inputMode="url"
                  autoComplete="off"
                />
              </div>
              <Button onClick={() => void onExtract()} disabled={importBusy}>
                {importBusy ? "Загрузка…" : "Найти цены"}
              </Button>
            </div>

            {importResult && (
              <div className="flex flex-col gap-3">
                <Alert>
                  <AlertDescription>{importResult.note}</AlertDescription>
                </Alert>

                {importResult.candidates.length === 0 ? (
                  <p className="text-muted-foreground text-pah-sm">
                    На странице не нашлось однозначных цен за 1M токенов.
                    Укажите их вручную в карточке модели.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {importResult.candidates.map((candidate, index) => (
                      <li
                        key={`${candidate.field}-${candidate.value}-${index}`}
                        className="rounded-md border p-2"
                      >
                        <div className="flex flex-wrap items-baseline gap-2">
                          <span className="text-pah-sm font-medium">
                            {IMPORT_FIELD_LABELS[candidate.field] ??
                              candidate.field}
                          </span>
                          <span className="font-mono text-pah-sm">
                            ${candidate.value}
                          </span>
                          <span className="text-muted-foreground text-pah-xs">
                            за 1M токенов
                          </span>
                        </div>
                        <p className="text-muted-foreground mt-1 line-clamp-2 text-pah-xs">
                          {candidate.snippet}
                        </p>
                        <Button
                          variant="outline"
                          size="sm"
                          className="mt-2"
                          onClick={() =>
                            applyCandidate(candidate.field, candidate.value)
                          }
                          disabled={!importModelId}
                        >
                          Подставить
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}

                {importResult.candidates.length > 0 && (
                  <div>
                    <Label htmlFor={importModelSelectId}>
                      К какой модели подставить
                    </Label>
                    <Select
                      value={importModelId}
                      onValueChange={setImportModelId}
                    >
                      <SelectTrigger id={importModelSelectId}>
                        <SelectValue placeholder="Выберите модель" />
                      </SelectTrigger>
                      <SelectContent>
                        {models.map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.display_name || m.external_model_id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                <p className="text-pah-xs text-muted-foreground">
                  Выберите модель выше и нажмите «Подставить» у нужного
                  значения: на странице обычно несколько тарифов, и брать первое
                  число автоматически нельзя. После подстановки проверьте цифры
                  и нажмите «Сохранить» в карточке модели — без этого цена не
                  попадёт в учёт расходов.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!loading && models.length > 0 && (
        <ul className="flex flex-col gap-4">
          {models.map((m) => {
            const p = currentPrice(m.id);
            return (
              <li key={m.id}>
                <ModelPriceCard
                  model={m}
                  price={p}
                  inputValue={inputs[m.id] ?? ""}
                  outputValue={outputs[m.id] ?? ""}
                  cacheReadValue={cacheReads[m.id] ?? ""}
                  cacheWriteValue={cacheWrites[m.id] ?? ""}
                  supportsReasoning={m.capabilities.includes("reasoning")}
                  reasoningBusy={Boolean(reasoningBusy[m.id])}
                  justSaved={saved === m.id}
                  onInputChange={(value) =>
                    setInputs((s) => ({ ...s, [m.id]: value }))
                  }
                  onOutputChange={(value) =>
                    setOutputs((s) => ({ ...s, [m.id]: value }))
                  }
                  onCacheReadChange={(value) =>
                    setCacheReads((s) => ({ ...s, [m.id]: value }))
                  }
                  onCacheWriteChange={(value) =>
                    setCacheWrites((s) => ({ ...s, [m.id]: value }))
                  }
                  onReasoningChange={(enabled) =>
                    void onReasoningChange(m, enabled)
                  }
                  onSubmit={(event) => onSave(event, m)}
                />
              </li>
            );
          })}
        </ul>
      )}
    </AppShell>
  );
}
