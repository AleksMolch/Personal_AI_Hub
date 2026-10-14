"use client";

// Навигация по разделам приложения.
//
// Назначение: единственное место, где перечислены разделы; используется и в
// общей оболочке AppShell, и в полноэкранных раскладках (чат), чтобы список
// разделов не дублировался и не расходился.
// Место в архитектуре: презентационный компонент, зависит только от роутера.
//
// Доступность: разметка — landmark `nav` со списком ссылок; текущий раздел
// помечается `aria-current="page"`, поэтому скринридер сообщает о положении
// пользователя без дополнительных подсказок.
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/** Разделы приложения в порядке отображения. */
export const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "Обзор" },
  { href: "/chat", label: "Чат" },
  { href: "/providers", label: "Провайдеры" },
  { href: "/models", label: "Модели и цены" },
  { href: "/usage", label: "Расходы" },
  { href: "/jobs", label: "Задачи" },
  { href: "/knowledge", label: "Базы знаний" },
  { href: "/tables", label: "Таблицы" },
  { href: "/profile", label: "Профиль" },
];

interface NavigationLinksProps {
  /** Ориентация списка: строка (шапка) или колонка (боковая панель). */
  orientation?: "horizontal" | "vertical";
  /** Дополнительные классы контейнера. */
  className?: string;
  /** Вызывается после перехода — например, чтобы закрыть мобильное меню. */
  onNavigate?: () => void;
}

/**
 * Список ссылок на разделы приложения.
 *
 * @param props Ориентация, классы и обработчик перехода.
 * @returns Навигационный список с подсветкой активного раздела.
 */
export function NavigationLinks({
  orientation = "horizontal",
  className,
  onNavigate,
}: NavigationLinksProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Основная навигация" className={className}>
      <ul
        className={cn(
          "flex gap-1",
          orientation === "horizontal"
            ? "flex-wrap items-center"
            : "flex-col items-stretch",
        )}
      >
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "inline-block rounded-md px-2 py-1 text-sm transition-colors",
                  isActive
                    ? "bg-secondary text-secondary-foreground font-medium"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
