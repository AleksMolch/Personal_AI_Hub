"use client";

// Онбординг: пошаговая настройка при первом входе.
//
// Назначение: провести пользователя от пустого состояния до первого успешного
// запроса: добавить провайдера с ключом, проверить соединение,
// синхронизировать каталог моделей, оценить бюджет и отправить пробное
// сообщение. Без этого шага пустая платформа выглядит неработающей.
//
// Место в архитектуре: клиентский мастер поверх существующих API. Он не хранит
// данные у себя и не обходит backend: каждый шаг вызывает те же эндпоинты, что
// и соответствующие страницы.
//
// Ключевые инварианты:
// 1. Ключ провайдера уходит только в POST /providers и нигде не сохраняется
//    в состоянии после успешного создания (в UI показывается маска).
// 2. Шаг бюджета можно пропустить: лимит — не обязательное условие работы.
// 3. Мастер можно закрыть; факт прохождения хранится в localStorage, чтобы не
//    возвращаться к нему на каждом входе.
import { useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { AddProviderStep } from "@/components/onboarding/steps/add-provider-step";
import { FirstMessageStep } from "@/components/onboarding/steps/first-message-step";
import { SetBudgetStep } from "@/components/onboarding/steps/set-budget-step";
import { SyncModelsStep } from "@/components/onboarding/steps/sync-models-step";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/** Ключ в localStorage: мастер пройден или пропущен. */
export const ONBOARDING_DONE_KEY = "pah_onboarding_done";

/** Описание шага мастера. */
interface OnboardingStep {
  /** Идентификатор шага (выбирает содержимое). */
  id: "provider" | "models" | "budget" | "message";
  /** Заголовок шага. */
  title: string;
  /** Можно ли пропустить шаг без потери работоспособности. */
  optional?: boolean;
}

/** Шаги мастера в порядке прохождения. */
const STEPS: OnboardingStep[] = [
  { id: "provider", title: "Добавить провайдера" },
  { id: "models", title: "Синхронизировать модели" },
  { id: "budget", title: "Настроить бюджет", optional: true },
  { id: "message", title: "Первый запрос" },
];

interface OnboardingWizardProps {
  /** Открыт ли мастер. */
  open: boolean;
  /** Вызывается при завершении или пропуске мастера. */
  onComplete: () => void;
  /** Идентификатор провайдера, созданного на первом шаге. */
  providerId: string | null;
  /** Сообщить мастеру о созданном провайдере. */
  onProviderCreated: (providerId: string) => void;
}

/**
 * Мастер первичной настройки.
 *
 * @param props Состояние открытия, обработчики и данные текущего провайдера.
 * @returns Модальное окно с индикатором прогресса и текущим шагом.
 */
export function OnboardingWizard({
  open,
  onComplete,
  providerId,
  onProviderCreated,
}: OnboardingWizardProps) {
  const [currentStep, setCurrentStep] = useState(0);

  const step = STEPS[currentStep];
  const progress = ((currentStep + 1) / STEPS.length) * 100;

  /** Переходит к следующему шагу или завершает мастер. */
  function next() {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      onComplete();
    }
  }

  /** Возврат на предыдущий шаг (на первом шаге недоступен). */
  function back() {
    setCurrentStep((prev) => Math.max(0, prev - 1));
  }

  return (
    <Dialog open={open} onOpenChange={() => undefined}>
      {/* hideClose: мастер закрывается только явной кнопкой «Пропустить»,
          чтобы случайный Escape не оставил настройку незавершённой. */}
      <DialogContent
        className="max-w-2xl"
        hideClose
        aria-describedby="onboarding-description"
      >
        <DialogHeader>
          <DialogTitle className="text-pah-2xl">
            Добро пожаловать в Personal AI Hub
          </DialogTitle>
          <DialogDescription id="onboarding-description">
            Настроим платформу за несколько шагов. Ключи хранятся только у вас и
            шифруются на сервере.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="space-y-2">
            <div className="text-muted-foreground flex justify-between text-pah-sm">
              <span>
                Шаг {currentStep + 1} из {STEPS.length}
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
            <Progress
              value={progress}
              aria-label={`Прогресс настройки: шаг ${currentStep + 1} из ${STEPS.length}`}
            />
          </div>

          {/* Индикатор шагов: пройденные отмечены галочкой, текущий выделен. */}
          <ol className="flex items-center justify-between gap-1">
            {STEPS.map((item, index) => {
              const done = index < currentStep;
              const active = index === currentStep;
              return (
                <li
                  key={item.id}
                  className="flex flex-1 items-center gap-2"
                  aria-current={active ? "step" : undefined}
                >
                  <span
                    className={cn(
                      "flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-pah-xs font-medium",
                      done &&
                        "border-primary bg-primary text-primary-foreground",
                      active && !done && "border-primary text-primary",
                      !done && !active && "border-muted text-muted-foreground",
                    )}
                  >
                    {done ? (
                      <CheckCircle2 className="size-4" aria-hidden="true" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span
                    className={cn(
                      "hidden text-pah-xs sm:inline",
                      active ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {item.title}
                  </span>
                </li>
              );
            })}
          </ol>

          <div className="bg-card rounded-lg border p-5">
            <h2 className="text-pah-lg mb-4 font-semibold">{step.title}</h2>

            {step.id === "provider" && (
              <AddProviderStep
                onDone={onProviderCreated}
                onNext={next}
                providerId={providerId}
              />
            )}
            {step.id === "models" && (
              <SyncModelsStep providerId={providerId} onNext={next} />
            )}
            {step.id === "budget" && <SetBudgetStep onNext={next} />}
            {step.id === "message" && <FirstMessageStep onNext={next} />}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex gap-2">
            {currentStep > 0 && (
              <Button variant="ghost" size="sm" onClick={back}>
                Назад
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            {step.optional && (
              <Button variant="ghost" size="sm" onClick={next}>
                Пропустить шаг
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={onComplete}>
              Пропустить настройку
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
