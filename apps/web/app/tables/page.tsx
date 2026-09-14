"use client";

import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  Asset,
  getToken,
  setToken,
  TablePreview,
  TableQueryResult,
} from "@/lib/api";

/**
 * Анализ таблиц: загрузка CSV/XLSX, просмотр схемы и SQL-запрос.
 */
export default function TablesPage() {
  const router = useRouter();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [sql, setSql] = useState("SELECT * FROM data LIMIT 20");
  const [result, setResult] = useState<TableQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAssets(await api.assets());
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

  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    if (!e.target.files?.length) return;
    setError(null);
    try {
      await api.uploadAsset(e.target.files[0]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить.");
    }
  }

  async function onOpen(id: string) {
    setCurrentId(id);
    setResult(null);
    try {
      setPreview(await api.tablePreview(id));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось открыть таблицу.",
      );
    }
  }

  async function onQuery(e: FormEvent) {
    e.preventDefault();
    if (!currentId) return;
    setError(null);
    try {
      setResult(await api.tableQuery(currentId, sql));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка запроса.");
    }
  }

  return (
    <main>
      <header className="row">
        <h1>Таблицы</h1>
        <div className="row">
          <Link href="/knowledge">Базы знаний</Link>
          <Link href="/usage">Расходы</Link>
        </div>
      </header>

      <div className="card">
        <label>
          Загрузить CSV/XLSX
          <input type="file" onChange={onUpload} accept=".csv,.xlsx,.xls" />
        </label>
      </div>

      <section className="grid">
        <div>
          <h2>Файлы</h2>
          {assets.map((a) => (
            <button
              key={a.id}
              className={currentId === a.id ? "kb-item active" : "kb-item"}
              onClick={() => onOpen(a.id)}
            >
              {a.original_name}
            </button>
          ))}
        </div>

        <div>
          {preview && (
            <div className="card">
              <h2>Схема ({preview.row_count} строк)</h2>
              <table>
                <thead>
                  <tr>
                    {preview.columns.map((c) => (
                      <th key={c.name}>
                        {c.name}
                        <div className="hint">{c.type}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, i) => (
                    <tr key={i}>
                      {preview.columns.map((c, j) => (
                        <td key={c.name}>{String(row[j] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview && (
            <form onSubmit={onQuery} className="card">
              <h2>SQL-запрос</h2>
              <textarea
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                rows={3}
              />
              <button type="submit">Выполнить</button>
            </form>
          )}

          {result && (
            <div className="card">
              <h2>Результат</h2>
              <table>
                <thead>
                  <tr>
                    {result.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i}>
                      {result.columns.map((c, j) => (
                        <td key={c}>{String(row[j] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
