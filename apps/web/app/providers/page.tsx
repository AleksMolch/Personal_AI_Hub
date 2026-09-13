"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, getToken, Provider, Preset, setToken } from "@/lib/api";

/**
 * Страница управления провайдерами.
 * Позволяет добавить провайдера (с пресетом), проверить соединение,
 * синхронизировать модели и удалить. Ключ отображается только маской.
 */
export default function ProvidersPage() {
  const router = useRouter();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [providerType, setProviderType] = useState("openai_compatible");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testMsg, setTestMsg] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const [p, pr] = await Promise.all([api.providers(), api.presets()]);
      setProviders(p);
      setPresets(pr);
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
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    void load();
  }, [load, router]);

  function onPresetChange(type: string) {
    setProviderType(type);
    const preset = presets.find((p) => p.provider_type === type);
    if (preset) setBaseUrl(preset.base_url);
  }

  async function onAdd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createProvider({
        provider_type: providerType,
        display_name: displayName || providerType,
        base_url: baseUrl,
        api_key: apiKey,
        currency:
          presets.find((p) => p.provider_type === providerType)?.currency ??
          "USD",
      });
      setDisplayName("");
      setApiKey("");
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось добавить провайдера.",
      );
    }
  }

  async function onTest(id: string) {
    setTestMsg((m) => ({ ...m, [id]: "Проверка…" }));
    try {
      const r = await api.testProvider(id);
      setTestMsg((m) => ({ ...m, [id]: r.message }));
    } catch (err) {
      setTestMsg((m) => ({
        ...m,
        [id]: err instanceof Error ? err.message : "Ошибка",
      }));
    }
  }

  async function onSync(id: string) {
    setTestMsg((m) => ({ ...m, [id]: "Синхронизация…" }));
    try {
      const models = await api.syncModels(id);
      setTestMsg((m) => ({ ...m, [id]: `Моделей: ${models.length}` }));
    } catch (err) {
      setTestMsg((m) => ({
        ...m,
        [id]: err instanceof Error ? err.message : "Ошибка",
      }));
    }
  }

  async function onDelete(id: string) {
    await api.deleteProvider(id);
    await load();
  }

  function logout() {
    setToken(null);
    router.push("/login");
  }

  return (
    <main>
      <header className="row">
        <h1>Провайдеры</h1>
        <div className="row">
          <Link href="/">Главная</Link>
          <button onClick={logout} className="link">
            Выйти
          </button>
        </div>
      </header>

      <form onSubmit={onAdd} className="card">
        <h2>Добавить провайдера</h2>
        <label>
          Пресет
          <select
            value={providerType}
            onChange={(e) => onPresetChange(e.target.value)}
          >
            {presets.map((p) => (
              <option key={p.provider_type} value={p.provider_type}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Название
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Мой провайдер"
          />
        </label>
        <label>
          Base URL
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.example.com/v1"
            required
          />
        </label>
        <label>
          API-ключ
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            required
          />
        </label>
        <button type="submit">Добавить</button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>

      <section>
        <h2>Подключённые</h2>
        {loading && <p>Загрузка…</p>}
        {!loading && providers.length === 0 && (
          <p className="hint">Пока нет провайдеров.</p>
        )}
        {providers.map((p) => (
          <div key={p.id} className="card provider">
            <div>
              <strong>{p.display_name}</strong>{" "}
              <span className="hint">
                {p.provider_type} · ключ {p.key_mask}
              </span>
              <div className="hint">{p.base_url}</div>
            </div>
            <div className="row">
              <button onClick={() => onTest(p.id)}>Проверить</button>
              <button onClick={() => onSync(p.id)}>Синхронизировать</button>
              <button className="danger" onClick={() => onDelete(p.id)}>
                Удалить
              </button>
            </div>
            {testMsg[p.id] && <p className="hint">{testMsg[p.id]}</p>}
          </div>
        ))}
      </section>
    </main>
  );
}
