"use client";

// Шаг 3 онбординга: дневной и месячный лимиты расходов.
//
// Назначение: предложить сразу выставить hard limit. Это необязательный шаг
// (его можно пропустить), но именно он превращает платформу в инструмент с
// контролем расходов: лимит проверяется ДО обращения к провайдеру.
//
// Место в архитектуре: шаг мастера поверх `api.getBudget` и `api.updateBudget`.
// Денежные значения передаются строками (Decimal на backend).
import { useEffect, useId, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";

interface SetBudgetStepProps {
  /** Переход к следующему шагу. */
  onNext: () => void;
}

/**
 * Форма лимитов бюджета.
 *
 * @param props Переход к следующему шагу.
 * @returns Поля дневного и месячного лимита с подсказкой о валюте.
 */
export function SetBudgetStep({ onNext }: SetBudgetStepProps) {
  const dailyId = useId();
  const monthlyId = useId();
  const [currency, setCurrency] = useState("USD");
  const [daily, setDaily] = useState("");
  const [monthly, setMonthly] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getBudget()
      .then((budget) => {
        setCurrency(budget.currency);
        setDaily(budget.daily_limit ?? "");
        setMonthly(budget.monthly_limit ?? "");
      })
      .catch(() => {
        // Бюджет создаётся лениво при первом обращении: отсутствие ответа
        // здесь не мешает продолжить настройку.
      });
  }, []);

  /** Сохраняет лимиты (пустое поле означает «без лимита»). */
  async function save() {
    setError(null);
    setBusy(true);
    try {
      await api.updateBudget({
        daily_limit: daily.trim() || null,
        monthly_limit: monthly.trim() || null,
      });
      setSaved(true);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Не удалось сохранить бюджет.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-pah-sm">
        Лимит проверяется до обращения к провайдеру: при превышении запрос не
        уходит и не списывает средства. Оставьте поле пустым, если лимит не
        нужен. Валюта бюджета: {currency}.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={dailyId}>Дневной лимит</Label>
          <Input
            id={dailyId}
            value={daily}
            onChange={(e) => setDaily(e.target.value)}
            placeholder="без лимита"
            inputMode="decimal"
          />
        </div>
        <div className="space-y-2">
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

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {saved && (
        <Alert variant="success">
          <AlertDescription>Бюджет сохранён.</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={save} disabled={busy}>
          {busy ? "Сохранение…" : "Сохранить бюджет"}
        </Button>
        <Button variant="outline" onClick={onNext}>
          Далее
        </Button>
      </div>
    </div>
  );
}
