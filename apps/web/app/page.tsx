"use client";

// Стартовая страница (обзор).
// Назначение: показать состояние подключения к backend, версию и быстрые
// переходы к разделам. Служит точкой входа после запуска стека.
// Место в архитектуре: клиентская страница; читает /version и /health/ready
// напрямую (без авторизации) и /auth/me при наличии токена.
import { useEffect, useState } from "react";
import Link from "next/link";

import {
  ONBOARDING_DONE_KEY,
  OnboardingWizard,
} from "@/components/onboarding/onboarding-wizard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getToken, User } from "@/lib/api";

/** Разделы приложения для быстрой навигации. */
const SECTIONS: { href: string; label: string; description: string }[] = [
  { href: "/chat", label: "Чат", description: "Диалоги с потоковым ответом" },
  {
    href: "/providers",
    label: "Провайдеры",
    description: "API-ключи и проверка соединения",
  },
  {
    href: "/models",
    label: "Модели и цены",
    description: "Каталог моделей и стоимость",
  },
  { href: "/usage", label: "Расходы", description: "Траты, токены и бюджеты" },
  { href: "/jobs", label: "Задачи", description: "Фоновые операции" },
  {
    href: "/knowledge",
    label: "Базы знаний",
    description: "Документы, OCR и RAG",
  },
  { href: "/tables", label: "Таблицы", description: "CSV/XLSX и SQL-запросы" },
];

export default function Home() {
  const [ready, setReady] = useState<"loading" | "ok" | "fail">("loading");
  const [version, setVersion] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingProviderId, setOnboardingProviderId] = useState<
    string | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
        const [v, readyRes] = await Promise.all([
          fetch(`${base}/api/v1/version`),
          fetch(`${base}/api/v1/health/ready`),
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
          if (cancelled) return;
          setUser(me);
          // Мастер показываем при первом входе: если пользователь его не
          // проходил и не пропускал, иначе пустая платформа выглядит нерабочей.
          if (!window.localStorage.getItem(ONBOARDING_DONE_KEY)) {
            setShowOnboarding(true);
          }
        } catch {
          // Токен недействителен — просто не показываем пользователя.
        }
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Завершает мастер и запоминает это, чтобы не показывать его снова. */
  function finishOnboarding() {
    window.localStorage.setItem(ONBOARDING_DONE_KEY, "1");
    setShowOnboarding(false);
  }

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      {user && (
        <OnboardingWizard
          open={showOnboarding}
          onComplete={finishOnboarding}
          providerId={onboardingProviderId}
          onProviderCreated={setOnboardingProviderId}
        />
      )}

      <header>
        <h1 className="text-pah-3xl font-semibold tracking-tight">
          Personal AI Hub
        </h1>
        <p className="text-muted-foreground mt-2">
          Локальная платформа для работы с языковыми моделями и документами.
          Self-hosted, ваши API-ключи хранятся только у вас.
        </p>
      </header>

      <div
        className="flex items-center gap-3 rounded-lg border px-4 py-3 text-sm"
        role="status"
        aria-live="polite"
      >
        {ready === "loading" ? (
          <Skeleton className="size-2.5 rounded-full" />
        ) : (
          <span
            aria-hidden="true"
            className={`size-2.5 rounded-full ${
              ready === "ok" ? "bg-success" : "bg-destructive"
            }`}
          />
        )}
        <span>
          {ready === "loading" && "Проверка подключения к API…"}
          {ready === "ok" && `API готов${version ? ` · v${version}` : ""}`}
          {ready === "fail" && "API недоступен — проверьте, что стек запущен"}
        </span>
      </div>

      {user ? (
        <>
          <p className="text-sm">
            Вы вошли как <strong>{user.username}</strong>.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {SECTIONS.map((section) => (
              <Card key={section.href}>
                <CardHeader>
                  <CardTitle>{section.label}</CardTitle>
                  <CardDescription>{section.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Button asChild variant="outline" size="sm">
                    <Link href={section.href}>Открыть</Link>
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Требуется вход</CardTitle>
            <CardDescription>
              Войдите или создайте администратора при первом запуске.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-3">
            <Button asChild>
              <Link href="/login">Войти</Link>
            </Button>
            <Badge variant="secondary">Ключи остаются у вас</Badge>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
