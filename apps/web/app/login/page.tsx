"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";

/**
 * Страница входа. Первый запуск: пользователь создаёт администратора
 * (bootstrap); далее — обычный вход.
 */
export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "bootstrap">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res =
        mode === "login"
          ? await api.login(username, password)
          : await api.bootstrap(username, password);
      setToken(res.access_token);
      router.push("/providers");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>Personal AI Hub</h1>
      <p>Локальная платформа для работы с языковыми моделями.</p>

      <form onSubmit={onSubmit} className="card">
        <div className="tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            className={mode === "login" ? "active" : ""}
            onClick={() => setMode("login")}
          >
            Вход
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "bootstrap"}
            className={mode === "bootstrap" ? "active" : ""}
            onClick={() => setMode("bootstrap")}
          >
            Первый запуск
          </button>
        </div>

        <label>
          Логин
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            minLength={3}
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            minLength={8}
          />
        </label>

        {mode === "bootstrap" && (
          <p className="hint">
            Создаст первого администратора. Доступно только при пустой базе.
          </p>
        )}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" disabled={loading}>
          {loading
            ? "Подождите…"
            : mode === "login"
              ? "Войти"
              : "Создать администратора"}
        </button>
      </form>
    </main>
  );
}
