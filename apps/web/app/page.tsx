"use client";

import { useEffect, useState } from "react";

type HealthState = "loading" | "ok" | "fail";

interface ApiInfo {
  version?: string;
  status?: string;
}

/**
 * Стартовая страница Этапа 1.
 * Показывает статус подключения к собственному backend API.
 * Браузер обращается только к нашему API, никогда напрямую к AI-провайдерам.
 */
export default function Home() {
  const [state, setState] = useState<HealthState>("loading");
  const [info, setInfo] = useState<ApiInfo>({});

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    let cancelled = false;

    async function check() {
      try {
        const [versionRes, readyRes] = await Promise.all([
          fetch(`${apiUrl}/api/v1/version`),
          fetch(`${apiUrl}/api/v1/health/ready`),
        ]);
        const version = await versionRes.json();
        const ready = await readyRes.json();
        if (cancelled) return;
        setInfo({ version: version.version, status: ready.status });
        setState(readyRes.ok ? "ok" : "fail");
      } catch {
        if (!cancelled) setState("fail");
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main>
      <h1>Personal AI Hub</h1>
      <p>
        Локальная платформа для работы с языковыми моделями и документами.
        Self-hosted, ваши API-ключи хранятся только у вас.
      </p>
      <div className="status" role="status" aria-live="polite">
        <span
          className={`dot ${state === "ok" ? "ok" : state === "fail" ? "fail" : ""}`}
        />
        {state === "loading" && "Проверка подключения к API…"}
        {state === "ok" &&
          `API готов${info.version ? ` · v${info.version}` : ""}`}
        {state === "fail" && "API недоступен — проверьте, что стек запущен"}
      </div>
    </main>
  );
}
