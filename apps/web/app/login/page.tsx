"use client";

// Страница входа и первого запуска.
// Назначение: аутентификация администратора (режим «Вход») и создание первого
// администратора при пустой базе (режим «Первый запуск»).
// Место в архитектуре: единственная публичная страница UI; после успеха
// сохраняет JWT в localStorage и переходит к разделу провайдеров.
import { FormEvent, useId, useState } from "react";
import { useRouter } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const usernameId = useId();
  const passwordId = useId();
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
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-6">
      <div className="text-center">
        <h1 className="text-pah-3xl font-semibold tracking-tight">
          Personal AI Hub
        </h1>
        <p className="text-muted-foreground mt-2">
          Локальная платформа для работы с языковыми моделями.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{mode === "login" ? "Вход" : "Первый запуск"}</CardTitle>
          <CardDescription>
            {mode === "login"
              ? "Введите логин и пароль администратора."
              : "Создание первого администратора при пустой базе."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Переключатель режимов: две взаимоисключающие формы входа. */}
          <div
            className="bg-muted mb-4 inline-flex rounded-lg p-0.5"
            role="tablist"
            aria-label="Режим входа"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                mode === "login"
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setMode("login")}
            >
              Вход
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "bootstrap"}
              className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                mode === "bootstrap"
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setMode("bootstrap")}
            >
              Первый запуск
            </button>
          </div>

          <form onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor={usernameId}>Логин</Label>
              <Input
                id={usernameId}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                minLength={3}
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor={passwordId}>Пароль</Label>
              <Input
                id={passwordId}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                minLength={8}
              />
            </div>

            {mode === "bootstrap" && (
              <p className="text-muted-foreground text-sm">
                Создаст первого администратора. Доступно только при пустой базе.
              </p>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" disabled={loading} className="w-full">
              {loading
                ? "Подождите…"
                : mode === "login"
                  ? "Войти"
                  : "Создать администратора"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
