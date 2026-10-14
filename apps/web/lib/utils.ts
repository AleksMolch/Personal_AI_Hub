// Утилита слияния CSS-классов.
// Назначение: объединять условные Tailwind-классы и корректно разрешать
// конфликты (например, "p-2" + "p-4" -> "p-4"), а не склеивать их подряд.
// Место в архитектуре: базовый помощник дизайн-системы, используется всеми
// компонентами apps/web/components.
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Объединяет классы, разрешая конфликты Tailwind в пользу последнего.
 *
 * @param inputs Классы: строки, массивы, объекты-условия или их комбинация.
 * @returns Итоговая строка классов без конфликтующих утилит.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
