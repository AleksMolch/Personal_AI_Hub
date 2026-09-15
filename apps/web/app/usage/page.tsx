"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  Budget,
  FxRate,
  getToken,
  setToken,
  UsageRecord,
  UsageSummary,
} from "@/lib/api";

/**
 * Дашборд расходов: сводка за день/месяц, лимиты, курсы валют и записи.
 * Все денежные значения отображаются как строки (Decimal) без потери точности.
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
      setDaily(b.daily_limit ?? "");
      setMonthly(b.monthly_limit ?? "");
    } catch (err) {
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

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await api.updateBudget({
        daily_limit: daily || null,
        monthly_limit: monthly || null,
      });
      setSaved(true);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить.");
    }
  }

  function money(v: string | null | undefined): string {
    if (v === null || v === undefined) return "—";
    return `${v} ${summary?.currency ?? ""}`.trim();
  }

  async function onAddRate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!rate.trim()) {
      setError("Укажите курс.");
      return;
    }
    try {
      await api.createFxRate({
        from_currency: fromCur,
        to_currency: toCur,
        rate: rate.trim(),
      });
      setRate("");
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось сохранить курс.",
      );
    }
  }

  return (
    <main>
      <header className="row">
        <h1>Расходы</h1>
        <div className="row">
          <Link href="/chat">Чат</Link>
          <Link href="/providers">Провайдеры</Link>
        </div>
      </header>

      {summary && (
        <section className="grid">
          <div className="card">
            <h2>Сегодня</h2>
            <p className="big">{money(summary.today_cost)}</p>
            <p className="hint">
              {summary.today_input_tokens} вх. / {summary.today_output_tokens}{" "}
              исх. токенов
            </p>
          </div>
          <div className="card">
            <h2>За месяц</h2>
            <p className="big">{money(summary.month_cost)}</p>
            <p className="hint">
              {summary.month_input_tokens} вх. / {summary.month_output_tokens}{" "}
              исх. токенов
            </p>
          </div>
          <div className="card">
            <h2>Лимиты</h2>
            <p className="hint">
              День: {money(summary.daily_limit)} (осталось{" "}
              {money(summary.daily_remaining)})
            </p>
            <p className="hint">
              Месяц: {money(summary.monthly_limit)} (осталось{" "}
              {money(summary.monthly_remaining)})
            </p>
          </div>
        </section>
      )}

      <form onSubmit={onSave} className="card">
        <h2>Бюджет</h2>
        <div className="row">
          <label>
            Дневной лимит
            <input
              value={daily}
              onChange={(e) => setDaily(e.target.value)}
              placeholder="без лимита"
              inputMode="decimal"
            />
          </label>
          <label>
            Месячный лимит
            <input
              value={monthly}
              onChange={(e) => setMonthly(e.target.value)}
              placeholder="без лимита"
              inputMode="decimal"
            />
          </label>
          <button type="submit">Сохранить</button>
        </div>
        {saved && <p className="hint">Сохранено.</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>

      <form onSubmit={onAddRate} className="card">
        <h2>Курсы валют</h2>
        <div className="row">
          <input
            value={fromCur}
            onChange={(e) => setFromCur(e.target.value.toUpperCase())}
            placeholder="Из"
            maxLength={3}
            aria-label="Валюта из"
          />
          <input
            value={toCur}
            onChange={(e) => setToCur(e.target.value.toUpperCase())}
            placeholder="В"
            maxLength={3}
            aria-label="Валюта в"
          />
          <input
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            placeholder="Курс (напр. 0.011)"
            inputMode="decimal"
            aria-label="Курс"
          />
          <button type="submit">Добавить</button>
        </div>
        {fxRates.length > 0 && (
          <div className="hint">
            {fxRates.slice(0, 5).map((f) => (
              <div key={f.id}>
                {f.from_currency} → {f.to_currency}: {f.rate}
              </div>
            ))}
          </div>
        )}
      </form>

      <section>
        <h2>Последние записи</h2>
        {records.length === 0 && <p className="hint">Записей пока нет.</p>}
        {records.map((r) => (
          <div key={r.id} className="card record">
            <span>
              {money(r.cost_amount)} · {r.cost_state}
            </span>
            <span className="hint">
              {new Date(r.occurred_at).toLocaleString()} ·{" "}
              {r.units_json.input_tokens ?? 0} вх. /{" "}
              {r.units_json.output_tokens ?? 0} исх.
            </span>
          </div>
        ))}
      </section>
    </main>
  );
}
