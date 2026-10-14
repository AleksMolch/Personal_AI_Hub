"use client";

// Страница «Задачи»: журнал фоновых операций (Job) с возможностью повтора и отмены.
//
// Назначение: показать пользователю состояние асинхронных задач Этапа 1
// (импорт/OCR/индексация документов, экспорт) и Этапа 2 (видео) и дать
// управлять ими — повторить «мёртвую» задачу (retryable/failed) или запросить
// отмену (queued/running).
//
// Место в архитектуре: клиентская страница Next.js (App Router) внутри
// AppShell. Данные получает ТОЛЬКО через типизированный клиент `@/lib/api`
// (`api.jobs`, `api.retryJob`, `api.cancelJob`) — браузер не обращается к
// внешним AI-провайдерам, вся работа идёт через собственный backend.
//
// Ключевые инварианты:
// 1. Статус — доменный словарь backend (`JobStatus` в packages/core):
//    queued, running, completed, failed, cancelled, retryable, плюс флаг
//    cancel_requested (запрошена отмена, но задача ещё выполняется).
//    Отображение статуса идёт через статический словарь STATUS_VARIANT, а не
//    через интерполяцию классов: Tailwind собирает классы статически и
//    `text-${status}` в CSS никогда не попадёт.
// 2. Статус передаётся текстом (русская подпись + код), а не только цветом:
//    цветовая индикация недоступна части пользователей (WCAG 1.4.1).
// 3. Список обновляется асинхронно (после retry/cancel), поэтому контейнер
//    списка помечен `aria-live="polite"`: скринридер объявит изменения.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getToken, Job, setToken } from "@/lib/api";

/** Вариант оформления бейджа: берётся из самого компонента `Badge`. */
type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>["variant"]>;

/**
 * Вариант `Badge` для каждого доменного статуса задачи.
 *
 * Статическая карта нужна и для типобезопасности, и для Tailwind: значения
 * перечислены литералами, поэтому классы попадают в собранный CSS.
 */
const STATUS_VARIANT: Record<string, BadgeVariant> = {
  completed: "success",
  failed: "destructive",
  cancelled: "outline",
  queued: "secondary",
  retryable: "secondary",
  running: "default",
};

/** Русские подписи статусов: пользователь не обязан знать английские коды. */
const STATUS_LABEL: Record<string, string> = {
  completed: "Завершено",
  failed: "Ошибка",
  cancelled: "Отменено",
  queued: "В очереди",
  retryable: "Ждёт повтора",
  running: "Выполняется",
};

/**
 * Возвращает вариант бейджа для статуса.
 *
 * @param status Статус задачи, пришедший с backend (может быть неизвестным,
 *   если backend добавит новое значение раньше UI).
 * @returns Вариант из STATUS_VARIANT или `outline` для неизвестного статуса.
 */
function statusVariant(status: string): BadgeVariant {
  return STATUS_VARIANT[status] ?? "outline";
}

/**
 * Человекочитаемая подпись статуса с сохранением исходного кода.
 *
 * @param status Статус задачи с backend.
 * @returns Строку вида «Выполняется (running)»; для неизвестного статуса —
 *   сам код без перевода, чтобы значение не потерялось.
 */
function statusLabel(status: string): string {
  const label = STATUS_LABEL[status];
  return label ? `${label} (${status})` : status;
}

/**
 * Страница списка задач.
 *
 * @returns Разметку журнала задач с фильтрацией действий по статусу.
 * @remarks
 * Побочные эффекты: чтение токена из localStorage, запросы к API и редирект
 * на `/login` при отсутствии токена или ответе 401.
 */
export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Отдельный флаг первой загрузки: по нему показывается skeleton, а не
  // пустое состояние, иначе пользователь на миг увидит «Задач пока нет».
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setJobs(await api.jobs());
    } catch (err) {
      // 401 — токен истёк или отозван: выходим из сессии (общий паттерн).
      if (
        err instanceof Error &&
        "status" in err &&
        (err as { status: number }).status === 401
      ) {
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

  /** Повторяет «мёртвую» задачу и перечитывает список. */
  async function onRetry(id: string) {
    try {
      await api.retryJob(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось повторить.");
    }
  }

  /** Запрашивает кооперативную отмену задачи и перечитывает список. */
  async function onCancel(id: string) {
    try {
      await api.cancelJob(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отменить.");
    }
  }

  return (
    <AppShell
      title="Задачи"
      description="Состояние фоновых операций: импорт, индексация и экспорт."
      actions={
        <>
          <Button variant="outline" size="sm" asChild>
            <Link href="/chat">Чат</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/usage">Расходы</Link>
          </Button>
        </>
      }
    >
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Ошибка</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col gap-4"
          aria-busy="true"
        >
          <span className="sr-only">Загрузка списка задач…</span>
          {[0, 1, 2].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-4 w-56" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-9 w-full sm:w-56" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <section
          aria-live="polite"
          aria-busy={false}
          className="flex flex-col gap-4"
        >
          <h2 className="sr-only">Список задач</h2>

          {jobs.length === 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Задач пока нет.</CardTitle>
                <CardDescription>
                  Задачи появляются автоматически: они создаются при загрузке
                  документов в базы знаний, индексации и экспорте данных. Когда
                  задача появится, здесь будут её статус, прогресс и действия.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/knowledge">Перейти в базы знаний</Link>
                </Button>
              </CardContent>
            </Card>
          )}

          {jobs.map((j) => {
            const isRunning = j.status === "running";
            const cancelRequested = j.cancel_requested === true;
            return (
              <Card key={j.id} className="sm:gap-0">
                <CardHeader>
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-pah-base break-all">
                      {j.type}
                    </CardTitle>
                    <Badge variant={statusVariant(j.status)}>
                      {statusLabel(j.status)}
                    </Badge>
                  </div>
                  <CardDescription>
                    {j.status === "completed"
                      ? `выполнено · ${j.attempts} поп.`
                      : j.error_code
                        ? `${j.error_code}${j.error_detail_safe ? ` · ${j.error_detail_safe}` : ""}`
                        : `прогресс ${j.progress}% · ${j.attempts} поп.`}
                  </CardDescription>
                </CardHeader>

                {isRunning && (
                  <CardContent className="flex flex-col gap-2">
                    {/* Прогресс дублируется текстом в описании выше: полоса
                        недоступна скринридеру и не заменяет числовое значение. */}
                    <Progress
                      value={j.progress}
                      aria-label={`Прогресс задачи ${j.type}`}
                    />
                  </CardContent>
                )}

                {cancelRequested && (
                  <CardContent>
                    <p className="text-pah-sm text-muted-foreground">
                      Запрошена отмена: задача остановится на ближайшей
                      контрольной точке.
                    </p>
                  </CardContent>
                )}

                <CardFooter className="flex-wrap gap-2">
                  {(j.status === "failed" || j.status === "retryable") && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => onRetry(j.id)}
                    >
                      Повторить
                    </Button>
                  )}
                  {(j.status === "queued" || j.status === "running") && (
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={isRunning && cancelRequested}
                      onClick={() => onCancel(j.id)}
                    >
                      {isRunning && cancelRequested
                        ? "Отменяется…"
                        : "Отменить"}
                    </Button>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </section>
      )}
    </AppShell>
  );
}
