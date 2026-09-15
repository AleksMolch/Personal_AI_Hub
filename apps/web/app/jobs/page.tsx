"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, getToken, Job, setToken } from "@/lib/api";

/**
 * Страница фоновых задач: статус, повтор и отмена.
 */
export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setJobs(await api.jobs());
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

  async function onRetry(id: string) {
    try {
      await api.retryJob(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось повторить.");
    }
  }

  async function onCancel(id: string) {
    try {
      await api.cancelJob(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отменить.");
    }
  }

  return (
    <main>
      <header className="row">
        <h1>Задачи</h1>
        <div className="row">
          <Link href="/chat">Чат</Link>
          <Link href="/usage">Расходы</Link>
        </div>
      </header>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {jobs.length === 0 && <p className="hint">Задач пока нет.</p>}
      {jobs.map((j) => (
        <div key={j.id} className="card record">
          <div>
            <strong>{j.type}</strong>{" "}
            <span className={`badge ${j.status}`}>{j.status}</span>
            <div className="hint">
              {j.status === "completed"
                ? `выполнено · ${j.attempts} поп.`
                : j.error_code
                  ? `${j.error_code}${j.error_detail_safe ? ` · ${j.error_detail_safe}` : ""}`
                  : `прогресс ${j.progress}% · ${j.attempts} поп.`}
            </div>
          </div>
          <div className="row">
            {(j.status === "failed" || j.status === "retryable") && (
              <button onClick={() => onRetry(j.id)}>Повторить</button>
            )}
            {(j.status === "queued" || j.status === "running") && (
              <button className="danger" onClick={() => onCancel(j.id)}>
                {j.status === "running" && j.cancel_requested
                  ? "Отменяется…"
                  : "Отменить"}
              </button>
            )}
          </div>
        </div>
      ))}
    </main>
  );
}
