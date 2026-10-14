"use client";

// Оболочка приложения: общая навигация и шапка для всех разделов.
//
// Назначение: единое расположение навигации и действия «Выйти», чтобы страницы
// не дублировали разметку и оставались согласованными.
// Место в архитектуре: клиентский компонент-контейнер; страница передаёт
// заголовок, описание, действия и содержимое. Данные не загружает.
import Link from "next/link";
import { useRouter } from "next/navigation";

import { NavigationLinks } from "@/components/navigation-links";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { setToken } from "@/lib/api";

interface AppShellProps {
  /** Заголовок страницы (h1). Должен совпадать с ожидаемым в E2E-тестах. */
  title: string;
  /** Короткое пояснение под заголовком. */
  description?: string;
  /** Действия в правой части шапки страницы. */
  actions?: React.ReactNode;
  /** Содержимое страницы. */
  children: React.ReactNode;
  /** Убрать ограничение ширины (для широких таблиц и раскладок). */
  fullWidth?: boolean;
}

/**
 * Общая оболочка страницы с навигацией и шапкой.
 *
 * @param props Заголовок, описание, действия и содержимое.
 * @returns Разметку страницы: шапка с навигацией плюс контент.
 */
export function AppShell({
  title,
  description,
  actions,
  children,
  fullWidth = false,
}: AppShellProps) {
  const router = useRouter();

  /** Сбрасывает токен и возвращает пользователя на страницу входа. */
  function logout() {
    setToken(null);
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      {/* Ссылка «к содержимому»: первая в порядке табуляции, позволяет
          пропустить навигацию с клавиатуры (WCAG 2.4.1). Видима только при
          фокусе. */}
      <a
        href="#main-content"
        className="bg-background sr-only rounded-md border px-3 py-2 text-sm focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50"
      >
        Перейти к содержимому
      </a>

      <header className="bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-40 border-b backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
          <span className="text-sm font-semibold whitespace-nowrap">
            Personal AI Hub
          </span>
          <NavigationLinks className="min-w-0 flex-1" />
          <Button variant="ghost" size="sm" asChild>
            <Link href="/profile">Профиль</Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={logout}>
            Выйти
          </Button>
        </div>
      </header>

      <main
        id="main-content"
        className={cn(
          "mx-auto flex flex-col gap-6 px-4 py-6",
          fullWidth ? "max-w-none" : "max-w-6xl",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-pah-2xl font-semibold tracking-tight">
              {title}
            </h1>
            {description && (
              <p className="text-muted-foreground mt-1 text-sm">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>

        {children}
      </main>
    </div>
  );
}
