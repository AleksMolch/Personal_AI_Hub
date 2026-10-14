"use client";

// Шаг 4 онбординга: проверка готовности и переход к первому запросу.
//
// Назначение: показать, что настройка завершена, и убедиться, что первый
// запрос действительно пройдёт. Отправлять пробное сообщение отсюда намеренно
// не стали: это платный вызов, а форма чата уже есть — дублировать её значило
// бы скрыть от пользователя, какая модель и какая цена будут использованы.
//
// Место в архитектуре: шаг мастера; проверяет состояние каталога через
// `api.models` и предлагает перейти в чат.
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ModelProfile } from "@/lib/api";

interface FirstMessageStepProps {
  /** Переход к следующему шагу (завершение мастера). */
  onNext: () => void;
}

/**
 * Итоговый шаг: проверка готовности к первому запросу.
 *
 * @param props Завершение мастера.
 * @returns Сводку готовности и кнопки перехода в чат или к ценам.
 */
export function FirstMessageStep({ onNext }: FirstMessageStepProps) {
  const router = useRouter();
  const [models, setModels] = useState<ModelProfile[] | null>(null);

  useEffect(() => {
    api
      .models()
      .then(setModels)
      .catch(() => setModels([]));
  }, []);

  /** Закрывает мастер и переходит в чат. */
  function openChat() {
    onNext();
    router.push("/chat");
  }

  /** Закрывает мастер и переходит к настройке цен. */
  function openPrices() {
    onNext();
    router.push("/models");
  }

  if (models === null) {
    return <Skeleton className="h-20 w-full" />;
  }

  const priced = models.filter((m) => m.has_price).length;

  if (models.length === 0) {
    return (
      <div className="space-y-4">
        <Alert variant="warning">
          <AlertDescription>
            Модели не найдены. Вернитесь на шаг синхронизации или добавьте
            модель вручную на странице «Провайдеры».
          </AlertDescription>
        </Alert>
        <Button variant="outline" onClick={onNext}>
          Завершить настройку
        </Button>
      </div>
    );
  }

  if (priced === 0) {
    return (
      <div className="space-y-4">
        <Alert variant="warning">
          <AlertDescription>
            Модели есть, но ни у одной не задана цена. Отправка сообщений будет
            заблокирована, пока цена не задана: платный вызов не должен уходить
            без учёта в бюджете.
          </AlertDescription>
        </Alert>
        <div className="flex flex-wrap gap-2">
          <Button onClick={openPrices}>Настроить цены</Button>
          <Button variant="outline" onClick={onNext}>
            Завершить настройку
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Alert variant="success">
        <AlertDescription>
          Всё готово: моделей с ценой — {priced}. Первый запрос можно отправить
          в чате; стоимость ответа появится под сообщением.
        </AlertDescription>
      </Alert>
      <div className="flex flex-wrap gap-2">
        <Button onClick={openChat}>Открыть чат</Button>
        <Button variant="outline" onClick={onNext}>
          Завершить настройку
        </Button>
      </div>
    </div>
  );
}
