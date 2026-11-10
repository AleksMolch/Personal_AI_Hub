"use client";

// Общая шапка приложения.
//
// Назначение: единые расположение и стиль навигации на всех экранах — бренд,
// разделы, тема, профиль и выход стоят в одном порядке и на одних отступах.
// Раньше чат рисовал собственную шапку, из-за чего меню «прыгало» при
// переходе между разделами.
//
// Место в архитектуре: клиентский компонент-контейнер; страницы передают
// только необязательный `leading` (например, кнопку списка диалогов).
// Данные не загружает.
import Link from "next/link";
import { useRouter } from "next/navigation";

import { NavigationLinks } from "@/components/navigation-links";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { setToken } from "@/lib/api";

interface AppHeaderProps {
  /** Дополнительный элемент слева (кнопка меню диалогов в чате). */
  leading?: React.ReactNode;
}

/**
 * Шапка с навигацией и действиями пользователя.
 *
 * @param props Необязательный элемент слева от бренда.
 * @returns «Стеклянную» шапку, одинаковую на всех страницах.
 */
export function AppHeader({ leading }: AppHeaderProps) {
  const router = useRouter();

  /** Сбрасывает токен и возвращает пользователя на страницу входа. */
  function logout() {
    setToken(null);
    router.push("/login");
  }

  return (
    <header className="bg-background/70 supports-[backdrop-filter]:bg-background/55 border-border/60 sticky top-0 z-40 border-b shadow-[0_1px_0_rgba(15,23,42,0.04)] backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2">
        {leading}
        <Link
          href="/"
          className="text-sm font-semibold whitespace-nowrap"
          aria-label="Personal AI Hub — на главную"
        >
          Personal AI Hub
        </Link>
        <NavigationLinks className="min-w-0 flex-1" />
        <ThemeToggle />
        <Button variant="ghost" size="sm" asChild>
          <Link href="/profile">Профиль</Link>
        </Button>
        <Button variant="ghost" size="sm" onClick={logout}>
          Выйти
        </Button>
      </div>
    </header>
  );
}
