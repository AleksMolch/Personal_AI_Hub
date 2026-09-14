"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, getToken, ModelProfile, Price, setToken } from "@/lib/api";

/**
 * Модели и цены: просмотр моделей и задание цены (за 1M токенов).
 */
export default function ModelsPage() {
  const router = useRouter();
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [prices, setPrices] = useState<Record<string, Price | null>>({});
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [outputs, setOutputs] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const ms = await api.models();
      setModels(ms);
      const priceMap: Record<string, Price | null> = {};
      for (const m of ms) {
        try {
          const list = await api.prices(m.id);
          priceMap[m.id] = list.length > 0 ? list[0] : null;
        } catch {
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
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка загрузки.");
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

  function currentPrice(modelId: string): Price | null {
    return prices[modelId] ?? null;
  }

  return (
    <main>
      <header className="row">
        <h1>Модели и цены</h1>
        <div className="row">
          <Link href="/chat">Чат</Link>
          <Link href="/providers">Провайдеры</Link>
        </div>
      </header>

      {models.length === 0 && (
        <p className="hint">
          Моделей нет. Сначала добавьте провайдера и синхронизируйте модели на
          странице «Провайдеры».
        </p>
      )}

      {models.map((m) => {
        const p = currentPrice(m.id);
        return (
          <div key={m.id} className="card">
            <div>
              <strong>{m.display_name}</strong>{" "}
              <span className="hint">{m.external_model_id}</span>
              <p className="hint">
                {p
                  ? `Текущая цена: $${p.input_per_million} / $${p.output_per_million} за 1M токенов (вход/выход)`
                  : "Цена не задана — чат с этой моделью заблокирован."}
              </p>
            </div>
            <form onSubmit={(e) => onSave(e, m)} className="row">
              <label>
                Цена входа, $/1M
                <input
                  value={inputs[m.id] ?? ""}
                  onChange={(e) =>
                    setInputs((s) => ({ ...s, [m.id]: e.target.value }))
                  }
                  placeholder={p?.input_per_million ?? "0.15"}
                  inputMode="decimal"
                />
              </label>
              <label>
                Цена выхода, $/1M
                <input
                  value={outputs[m.id] ?? ""}
                  onChange={(e) =>
                    setOutputs((s) => ({ ...s, [m.id]: e.target.value }))
                  }
                  placeholder={p?.output_per_million ?? "0.60"}
                  inputMode="decimal"
                />
              </label>
              <button type="submit">Сохранить</button>
            </form>
            {saved === m.id && <p className="hint">Цена сохранена.</p>}
          </div>
        );
      })}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
