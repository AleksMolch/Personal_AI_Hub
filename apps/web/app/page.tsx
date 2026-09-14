"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, getToken, User } from "@/lib/api";

/**
 * Стартовая страница: показывает статус подключения к backend и навигацию.
 */
export default function Home() {
  const [ready, setReady] = useState<"loading" | "ok" | "fail">("loading");
  const [version, setVersion] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const [v, readyRes] = await Promise.all([
          fetch(
            `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/version`,
          ),
          fetch(
            `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/health/ready`,
          ),
        ]);
        const vJson = await v.json();
        const rJson = await readyRes.json();
        if (cancelled) return;
        setVersion(vJson.version);
        setReady(rJson.status === "ready" ? "ok" : "fail");
      } catch {
        if (!cancelled) setReady("fail");
      }

      if (getToken()) {
        try {
          const me = await api.me();
          if (!cancelled) setUser(me);
        } catch {
          // токен недействителен — просто не показываем пользователя
        }
      }
    }
    void check();
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
          className={`dot ${ready === "ok" ? "ok" : ready === "fail" ? "fail" : ""}`}
        />
        {ready === "loading" && "Проверка подключения к API…"}
        {ready === "ok" && `API готов${version ? ` · v${version}` : ""}`}
        {ready === "fail" && "API недоступен — проверьте, что стек запущен"}
      </div>

      <div className="card">
        {user ? (
          <>
            <p>
              Вы вошли как <strong>{user.username}</strong>.
            </p>
            <div className="row">
              <Link href="/chat">Открыть чат</Link>
              <Link href="/providers">Настроить провайдеров</Link>
              <Link href="/usage">Расходы</Link>
              <Link href="/jobs">Задачи</Link>
            </div>
          </>
        ) : (
          <div className="row">
            <Link href="/login">Войти</Link>
          </div>
        )}
      </div>
    </main>
  );
}
