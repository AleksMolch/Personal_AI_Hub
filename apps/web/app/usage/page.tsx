"use client";

// Дашборд расходов — центральный экран продукта (экономическая дисциплина).
//
// Назначение: показать пользователю, сколько он потратил сегодня и за месяц,
// сколько токенов израсходовано, насколько он приблизился к лимитам, дать
// возможность изменить бюджет, добавить курс валюты и посмотреть последние
// записи расхода с честной пометкой «оценка/факт».
//
// Место в архитектуре: клиентская страница (`"use client"`). Данные приходят
// ТОЛЬКО из собственного backend через типизированный клиент `@/lib/api`
// (usageSummary/getBudget/usageRecords/fxRates, updateBudget, createFxRate) —
// браузер не обращается к внешним AI-провайдерам и не владеет ключами.
//
// Инварианты предметной области (см. AGENTS.md):
// 1. Деньги приходят с backend как Decimal-строки. Они НИКОГДА не приводятся
//    к number для отображения: `money()` лишь добавляет код валюты, а точное
//    значение остаётся строкой вплоть до текста в DOM. Даже когда для ширины
//    полосы прогресса нужно число, оно вычисляется отдельной функцией и не
//    подменяет собой отображаемую строку.
// 2. Символ валюты не зашит в разметку: валюта берётся из `summary`/`budget`
//    (backend по умолчанию считает в USD и конвертирует через FxRate).
// 3. `cost_state` записи (estimated/actual/reconciled/unknown) сохраняется при
//    передаче в CostBadge, поэтому оценка никогда не выглядит как факт.
//
// Доступность: h1 рендерит AppShell (текст «Расходы» проверяется E2E-тестом);
// сводка — именованный регион `aria-labelledby`; поля связаны с Label по
// `useId()`; ошибки объявляются через `role="alert"`, подтверждение сохранения
// — через `aria-live="polite"`.
import { FormEvent, useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CostBadge, type CostStatus } from "@/components/ui/cost-badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  Budget,
  FxRate,
  getToken,
  isValidDecimal,
  normalizeDecimalInput,
  setToken,
  UsageRecord,
  UsageSummary,
} from "@/lib/api";

/** Ширина полосы прогресса в процентах (не более 100 при перерасходе). */
const MAX_PROGRESS = 100;

/** Класс крупной денежной суммы: один источник стиля для всех трёх метрик. */
const MONEY_CLASS = "text-pah-2xl font-semibold tracking-tight tabular-nums";

/**
 * Приводит произвольную строку состояния расчёта к типу CostStatus.
 *
 * Backend отдаёт `cost_state` как строку, поэтому неизвестное значение
 * трактуется как "unknown": лучше показать «Цена не задана», чем случайно
 * выдать оценку за факт.
 *
 * @param state Значение `cost_state` из UsageRecord.
 * @returns Сужаемое состояние стоимости для CostBadge.
 */
function toCostStatus(state: string): CostStatus {
  switch (state) {
    case "estimated":
    case "actual":
    case "reconciled":
    case "unknown":
      return state;
    default:
      return "unknown";
  }
}

/**
 * Извлекает целое число токенов из units_json.
 *
 * units_json описан как Record<string, number>, но приходит из JSON, поэтому
 * значение проверяется и нечисловое превращается в 0.
 *
 * @param units Словарь единиц расхода записи.
 * @param key Имя ключа (input_tokens, output_tokens, reasoning_tokens).
 * @returns Количество токенов или 0, если ключа нет.
 */
function tokenCount(units: Record<string, number>, key: string): number {
  const value = units[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/**
 * Считает долю израсходованного бюджета для полосы прогресса.
 *
 * Число нужно только для ширины индикатора; пользователю всегда показываются
 * Decimal-строки лимита и остатка. Если лимит не задан, суммы нет или лимит
 * нулевой — возвращается null, и полоса не рисуется.
 *
 * @param spent Потраченная сумма (Decimal-строка).
 * @param limit Лимит (Decimal-строка или null).
 * @returns Процент 0..100 или null, если прогресс вычислить нельзя.
 */
function usagePercent(spent: string, limit: string | null): number | null {
  if (!limit) return null;
  const spentValue = Number(spent);
  const limitValue = Number(limit);
  if (!Number.isFinite(spentValue) || !Number.isFinite(limitValue)) return null;
  if (limitValue <= 0) return null;
  const percent = (spentValue / limitValue) * MAX_PROGRESS;
  return Math.min(Math.max(percent, 0), MAX_PROGRESS);
}

/**
 * Состояние первой загрузки данных.
 *
 * `loading` — запросы ещё не завершились (показываем скелетон);
 * `ready` — данные получены (либо загрузка завершилась ошибкой, которая
 * отображается отдельным Alert, а не бесконечным скелетоном).
 */
type LoadState = "loading" | "ready";

/**
 * Страница расходов: сводка, лимиты, бюджет, курсы валют и последние записи.
 *
 * Все четыре запроса выполняются параллельно (`Promise.all`), поэтому экран
 * наполняется одним обновлением состояния. При 401 токен очищается и
 * пользователь возвращается на страницу входа.
 *
 * @returns Разметку дашборда расходов внутри общей оболочки AppShell.
 */
export default function UsagePage() {
  const router = useRouter();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [fxRates, setFxRates] = useState<FxRate[]>([]);
  const [daily, setDaily] = useState("");
  const [monthly, setMonthly] = useState("");
  const [fromCur, setFromCur] = useState("RUB");
  const [toCur, setToCur] = useState("USD");
  const [rate, setRate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  // Стабильные id для связи Label ↔ Input (доступность формы).
  const dailyId = useId();
  const monthlyId = useId();
  const fromCurId = useId();
  const toCurId = useId();
  const rateId = useId();

  /** Загружает сводку, бюджет, записи и курсы одной пачкой параллельных запросов. */
  async function load() {
    try {
      const [s, b, r, f] = await Promise.all([
        api.usageSummary(),
        api.getBudget(),
        api.usageRecords(),
        api.fxRates(),
      ]);
      setSummary(s);
      setBudget(b);
      setRecords(r);
      setFxRates(f);
      // Поля формы заполняются фактическим бюджетом; пустая строка означает
      // «лимит не задан» и соответствует placeholder «без лимита».
      setDaily(b.daily_limit ?? "");
      setMonthly(b.monthly_limit ?? "");
    } catch (err) {
      // 401 — токен истёк: чистим его и уводим на вход, а не показываем ошибку.
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
      // Скелетон снимается в любом случае, иначе ошибка оставила бы его навсегда.
      setLoadState("ready");
    }
  }

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch на mount
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  /**
   * Сохраняет лимиты бюджета.
   *
   * Пустое поле отправляется как `null` — это осознанный «без лимита», а не 0.
   *
   * @param e Событие отправки формы бюджета.
   */
  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    // Запятая — обычный десятичный разделитель в русской локали; backend
    // принимает оба варианта, но нормализуем заранее, чтобы не зависеть от него.
    const dailyLimit = normalizeDecimalInput(daily);
    const monthlyLimit = normalizeDecimalInput(monthly);
    if (
      (dailyLimit && !isValidDecimal(dailyLimit)) ||
      (monthlyLimit && !isValidDecimal(monthlyLimit))
    ) {
      setError("Лимит должен быть неотрицательным числом, например 5 или 5,5.");
      return;
    }
    try {
      await api.updateBudget({
        daily_limit: dailyLimit || null,
        monthly_limit: monthlyLimit || null,
      });
      setSaved(true);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить.");
    }
  }

  /**
   * Собирает отображаемую денежную строку.
   *
   * Значение НЕ преобразуется в число: Decimal-строка backend'а остаётся
   * строкой, к ней лишь добавляется код валюты бюджета.
   *
   * @param v Сумма (Decimal-строка) либо null/undefined, если лимит не задан.
   * @returns Строку вида `12.5 USD` или «—» для отсутствующего значения.
   */
  function money(v: string | null | undefined): string {
    if (v === null || v === undefined) return "—";
    return `${v} ${summary?.currency ?? ""}`.trim();
  }

  /**
   * Добавляет курс валюты.
   *
   * Курс обязателен: пустое значение даёт понятную ошибку «Укажите курс.»
   * вместо запроса с пустым телом.
   *
   * @param e Событие отправки формы курса.
   */
  async function onAddRate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    // Курс тоже принимаем с запятой: «0,011» — естественный ввод.
    const normalizedRate = normalizeDecimalInput(rate);
    if (!normalizedRate) {
      setError("Укажите курс.");
      return;
    }
    if (!isValidDecimal(normalizedRate)) {
      setError(
        "Курс должен быть положительным числом, например 0.011 или 0,011.",
      );
      return;
    }
    try {
      await api.createFxRate({
        from_currency: fromCur,
        to_currency: toCur,
        rate: normalizedRate,
      });
      setRate("");
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось сохранить курс.",
      );
    }
  }

  // Валюта бюджета для меток стоимости; до ответа backend'а используем то, что
  // уже пришло в бюджете, иначе оставляем undefined (CostBadge не подставит
  // чужой символ валюты).
  const currency = summary?.currency ?? budget?.currency;
  const dailyPercent = summary
    ? usagePercent(summary.today_cost, summary.daily_limit)
    : null;
  const monthlyPercent = summary
    ? usagePercent(summary.month_cost, summary.monthly_limit)
    : null;

  return (
    <AppShell
      title="Расходы"
      description="Траты, токены и лимиты. Это расчёт по токенам и сохранённому прайсу, а не счёт провайдера."
      actions={
        <Button variant="outline" size="sm" onClick={() => void load()}>
          Обновить
        </Button>
      }
    >
      <div className="flex flex-col gap-6">
        {/* Ошибка загрузки или валидации: Alert уже имеет role="alert". */}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Первая загрузка: показываем структуру экрана, чтобы не было «прыжка». */}
        {loadState === "loading" && (
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Skeleton className="h-8 w-32" />
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-2/3" />
                </CardContent>
              </Card>
            ))}
          </section>
        )}

        {/* Сводка за сегодня/месяц и остатки лимитов — один именованный регион. */}
        {summary && (
          <section
            aria-labelledby="usage-summary-title"
            className="flex flex-col gap-3"
          >
            <h2 id="usage-summary-title" className="sr-only">
              Сводка расходов
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Card>
                <CardHeader>
                  <CardTitle>Сегодня</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                  <p className={MONEY_CLASS}>{money(summary.today_cost)}</p>
                  <p className="text-muted-foreground text-pah-sm">
                    {summary.today_input_tokens} вх. /{" "}
                    {summary.today_output_tokens} исх. токенов
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>За месяц</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2">
                  <p className={MONEY_CLASS}>{money(summary.month_cost)}</p>
                  <p className="text-muted-foreground text-pah-sm">
                    {summary.month_input_tokens} вх. /{" "}
                    {summary.month_output_tokens} исх. токенов
                  </p>
                </CardContent>
              </Card>

              <Card className="sm:col-span-2 lg:col-span-1">
                <CardHeader>
                  <CardTitle>Лимиты</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-4">
                  <div className="flex flex-col gap-2">
                    <p className="text-muted-foreground text-pah-sm">
                      День: {money(summary.daily_limit)} (осталось{" "}
                      {money(summary.daily_remaining)})
                    </p>
                    {/* Полоса строится только при заданном лимите: без лимита
                        процент не имеет смысла. */}
                    {dailyPercent !== null && (
                      <Progress
                        value={dailyPercent}
                        aria-label="Израсходовано дневного лимита"
                      />
                    )}
                  </div>
                  <div className="flex flex-col gap-2">
                    <p className="text-muted-foreground text-pah-sm">
                      Месяц: {money(summary.monthly_limit)} (осталось{" "}
                      {money(summary.monthly_remaining)})
                    </p>
                    {monthlyPercent !== null && (
                      <Progress
                        value={monthlyPercent}
                        aria-label="Израсходовано месячного лимита"
                      />
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          </section>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Бюджет</CardTitle>
            <CardDescription>
              Пустое поле означает «без лимита»; лимит выражается в валюте
              бюджета{currency ? ` (${currency})` : ""}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSave} className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-2">
                  <Label htmlFor={dailyId}>Дневной лимит</Label>
                  <Input
                    id={dailyId}
                    value={daily}
                    onChange={(e) => setDaily(e.target.value)}
                    placeholder="без лимита"
                    inputMode="decimal"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor={monthlyId}>Месячный лимит</Label>
                  <Input
                    id={monthlyId}
                    value={monthly}
                    onChange={(e) => setMonthly(e.target.value)}
                    placeholder="без лимита"
                    inputMode="decimal"
                  />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit">Сохранить</Button>
                {/* Подтверждение объявляется скринридером вежливо и один раз. */}
                <p
                  aria-live="polite"
                  className="text-muted-foreground text-pah-sm"
                >
                  {saved ? "Сохранено." : ""}
                </p>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Курсы валют</CardTitle>
            <CardDescription>
              Курс нужен, чтобы приводить стоимость провайдера к валюте бюджета.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <form onSubmit={onAddRate} className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="flex flex-col gap-2">
                  <Label htmlFor={fromCurId}>Из</Label>
                  <Input
                    id={fromCurId}
                    value={fromCur}
                    onChange={(e) => setFromCur(e.target.value.toUpperCase())}
                    placeholder="Из"
                    maxLength={3}
                    aria-label="Валюта из"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor={toCurId}>В</Label>
                  <Input
                    id={toCurId}
                    value={toCur}
                    onChange={(e) => setToCur(e.target.value.toUpperCase())}
                    placeholder="В"
                    maxLength={3}
                    aria-label="Валюта в"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor={rateId}>Курс</Label>
                  <Input
                    id={rateId}
                    value={rate}
                    onChange={(e) => setRate(e.target.value)}
                    placeholder="Курс (напр. 0.011)"
                    inputMode="decimal"
                    aria-label="Курс"
                  />
                </div>
              </div>
              <div>
                <Button type="submit" variant="secondary">
                  Добавить
                </Button>
              </div>
            </form>

            {fxRates.length > 0 && (
              <div className="flex flex-col gap-1">
                {fxRates.slice(0, 5).map((f) => (
                  <div key={f.id} className="text-muted-foreground text-pah-sm">
                    {f.from_currency} → {f.to_currency}: {f.rate}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <section className="flex flex-col gap-3">
          <h2 className="text-pah-lg font-semibold">Последние записи</h2>
          {records.length === 0 ? (
            <Card>
              <CardContent className="text-muted-foreground py-2 text-pah-sm">
                Записей пока нет.
              </CardContent>
            </Card>
          ) : (
            <ul className="flex flex-col gap-2">
              {records.map((r) => {
                const tokensIn = tokenCount(r.units_json, "input_tokens");
                const tokensOut = tokenCount(r.units_json, "output_tokens");
                // Токены рассуждений уже входят в выходные; показываем их
                // отдельно, чтобы не создавать впечатление двойного расхода.
                const reasoning = tokenCount(r.units_json, "reasoning_tokens");
                return (
                  <li key={r.id}>
                    <Card className="py-3">
                      <CardContent className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="flex flex-wrap items-center gap-2">
                          {/* CostBadge хранит честность оценки: estimated
                              помечается «≈» и пунктиром, unknown — «Цена не
                              задана». */}
                          <CostBadge
                            cost={r.cost_amount}
                            status={toCostStatus(r.cost_state)}
                            currency={summary?.currency}
                            tokensIn={tokensIn}
                            tokensOut={tokensOut}
                            reasoningTokens={reasoning}
                            size="sm"
                          />
                          {/* Точная Decimal-строка с валютой — на случай, когда
                              нужна сумма «как есть», без сокращения. */}
                          <span className="text-pah-sm tabular-nums">
                            {money(r.cost_amount)}
                          </span>
                        </div>
                        <span className="text-muted-foreground text-pah-sm">
                          {new Date(r.occurred_at).toLocaleString()} ·{" "}
                          {tokensIn} вх. / {tokensOut} исх.
                        </span>
                      </CardContent>
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}
