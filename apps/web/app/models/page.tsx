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
import { Skeleton } from "@/components/ui/skeleton";
import { api, getToken, ModelProfile, Price, setToken } from "@/lib/api";

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

/** Ключи для трёх карточек-заглушек (фиксированные, без индексов массива). */
const SKELETON_KEYS = ["first", "second", "third"] as const;

interface ModelPriceCardProps {
  /** Модель из каталога backend. */
  model: ModelProfile;
  /** Действующая цена модели или null, если цена ещё не задана. */
  price: Price | null;
  /** Текущее значение поля «цена входа». */
  inputValue: string;
  /** Текущее значение поля «цена выхода». */
  outputValue: string;
  /** Признак того, что цена этой модели только что сохранена. */
  justSaved: boolean;
  /** Изменение поля «цена входа». */
  onInputChange: (value: string) => void;
  /** Изменение поля «цена выхода». */
  onOutputChange: (value: string) => void;
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
  justSaved,
  onInputChange,
  onOutputChange,
  onSubmit,
}: ModelPriceCardProps) {
  // useId даёт уникальные id для пар label/input: карточек на странице много,
  // а id в документе должны быть уникальны, иначе label свяжется не с тем полем.
  const fieldId = useId();
  const inputId = `${fieldId}-input`;
  const outputId = `${fieldId}-output`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{model.display_name}</CardTitle>
        <CardDescription className="font-mono break-all">
          {model.external_model_id}
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <p className={price ? PRICE_TEXT_CLASS.set : PRICE_TEXT_CLASS.missing}>
          {price
            ? `Текущая цена: $${price.input_per_million} / $${price.output_per_million} за 1M токенов (вход/выход)`
            : MISSING_PRICE_TEXT}
        </p>

        {/* Форма не имеет видимой подписи, поэтому имя задано через aria-label. */}
        <form
          onSubmit={onSubmit}
          aria-label={`Цена модели ${model.display_name}`}
          className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end"
        >
          <div className="flex w-full flex-col gap-1.5 sm:w-40">
            <Label htmlFor={inputId}>Цена входа, $/1M</Label>
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

          <Button type="submit" className="w-full sm:w-auto">
            Сохранить
          </Button>
        </form>

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
    const input = inputs[model.id]?.trim();
    const output = outputs[model.id]?.trim();
    if (!input || !output) {
      setError("Укажите цену входа и выхода.");
      return;
    }
    try {
      await api.createPrice({
        model_profile_id: model.id,
        input_per_million: input,
        output_per_million: output,
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
                  justSaved={saved === m.id}
                  onInputChange={(value) =>
                    setInputs((s) => ({ ...s, [m.id]: value }))
                  }
                  onOutputChange={(value) =>
                    setOutputs((s) => ({ ...s, [m.id]: value }))
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
