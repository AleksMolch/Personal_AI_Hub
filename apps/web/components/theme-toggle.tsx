"use client";

// Переключатель светлой и тёмной темы.
//
// Назначение: дать пользователю выбрать тему и запомнить выбор между
// перезагрузками. Тёмные токены уже описаны в `tokens.css` (`.dark`), поэтому
// компонент только переключает класс на `<html>`.
//
// Место в архитектуре: примитив интерфейса; используется в шапке чата и в
// общей оболочке. Данные не загружает, обращается только к localStorage.
//
// Почему `useSyncExternalStore`, а не `useState` + `useEffect`: тема — это
// внешнее состояние (класс на `<html>` + localStorage). Чтение его в эффекте и
// синхронный setState приводили к каскадному рендеру (запрещено линтером), а
// подписка на изменение даёт корректное значение и при гидратации.
import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

/** Ключ localStorage: выбранная тема. */
export const THEME_KEY = "pah_theme";

/** Событие внутри вкладки: localStorage не присылает его самому себе. */
const CHANGE_EVENT = "pah-theme-change";

/** Допустимые темы. */
type Theme = "light" | "dark";

/** Читает текущую тему из класса на `<html>`. */
function readTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Подписка на изменения темы (другая вкладка или этот же компонент). */
function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(CHANGE_EVENT, onChange);
  };
}

/** Применяет тему к документу. */
function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}

/**
 * Кнопка переключения темы с запоминанием выбора.
 *
 * @returns Кнопку с иконкой луны/солнца и понятной подписью для скринридера.
 */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "light");
  const isDark = theme === "dark";

  /** Переключает тему и сохраняет выбор. */
  function toggle() {
    const next: Theme = isDark ? "light" : "dark";
    applyTheme(next);
    window.localStorage.setItem(THEME_KEY, next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggle}
      aria-pressed={isDark}
      aria-label={isDark ? "Включить светлую тему" : "Включить тёмную тему"}
      title={isDark ? "Светлая тема" : "Тёмная тема"}
    >
      {isDark ? <Sun /> : <Moon />}
    </Button>
  );
}
