"use client";

// Шаг 2 онбординга: синхронизация каталога моделей.
//
// Назначение: получить модели провайдера в каталог, чтобы пользователь мог
// выбрать, с какой работать. Показ признака цены обязателен: без цены платный
// вызов заблокирован, и пользователь должен узнать это здесь, а не при первой
// отправке сообщения.
//
// Место в архитектуре: шаг мастера поверх `api.syncModels` и `api.models`.
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, ModelProfile } from "@/lib/api";

interface SyncModelsStepProps {
  /** Провайдер, созданный на предыдущем шаге. */
  providerId: string | null;
  /** Переход к следующему шагу. */
  onNext: () => void;
}

/**
 * Синхронизация моделей и краткая сводка по каталогу.
 *
 * @param props Идентификатор провайдера и переход к следующему шагу.
 * @returns Кнопку синхронизации, счётчики моделей и предупреждение о ценах.
 */
export function SyncModelsStep({ providerId, onNext }: SyncModelsStepProps) {
  const [models, setModels] = useState<ModelProfile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Запускает синхронизацию и перечитывает каталог. */
  async function sync() {
    if (!providerId) {
      setError("Провайдер не найден. Вернитесь на предыдущий шаг.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api.syncModels(providerId);
      setModels(await api.models());
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Не удалось синхронизировать.",
      );
    } finally {
      setBusy(false);
    }
  }

  const priced = models?.filter((m) => m.has_price).length ?? 0;
  const total = models?.length ?? 0;

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-pah-sm">
        Синхронизация запрашивает список моделей у провайдера и добавляет их в
        каталог. Цены, если провайдер их отдаёт, импортируются автоматически.
      </p>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {models === null ? (
        <Skeleton className="h-9 w-48" />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">Моделей: {total}</Badge>
          <Badge variant={priced > 0 ? "success" : "warning"}>
            С ценой: {priced}
          </Badge>
        </div>
      )}

      {models !== null && total > 0 && priced === 0 && (
        <Alert variant="warning">
          <AlertDescription>
            Ни у одной модели нет цены — провайдер не отдал прайс. Задайте цену
            на странице «Модели и цены», иначе отправка сообщений будет
            заблокирована (PRICE_REQUIRED).
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={sync} disabled={busy}>
          {busy ? "Синхронизация…" : "Синхронизировать модели"}
        </Button>
        {models !== null && total > 0 && (
          <Button variant="outline" onClick={onNext}>
            Далее
          </Button>
        )}
      </div>
    </div>
  );
}
