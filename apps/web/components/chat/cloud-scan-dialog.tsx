"use client";

// Диалог предупреждения перед отправкой в облачном режиме (ADR-0008).
//
// Назначение: показать, какие категории данных найдены локально, и дать
// пользователю выбор — отправить как есть, перейти в гибрид (там текст
// очищается) или отменить отправку. Это UX-предупреждение, а не гарантия:
// детектор может ошибаться, поэтому формулировки не обещают безопасности.
//
// Место в архитектуре: представление; решение и отправку выполняет страница
// чата. Исходные значения сюда не передаются — только категории и счётчики.
import { ShieldAlert, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** Результат локального сканирования: категории без исходных значений. */
export interface CloudScanResult {
  categories: { category: string; count: number }[];
  has_secret: boolean;
}

interface CloudScanDialogProps {
  /** Открыт ли диалог. */
  open: boolean;
  /** Найденные категории; null — диалог закрыт. */
  scan: CloudScanResult | null;
  /** Идёт подготовка гибрида — кнопки блокируются. */
  busy?: boolean;
  /** Отмена: ничего не отправляется. */
  onCancel: () => void;
  /** Отправить исходный текст, несмотря на предупреждение. */
  onSendAnyway: () => void;
  /** Перейти в гибрид и показать preview очищенного текста. */
  onUseHybrid: () => void;
}

/** Человекочитаемые названия категорий. */
const CATEGORY_LABELS: Record<string, string> = {
  email: "E-mail",
  phone: "Телефон",
  url: "Ссылка",
  org: "Организация",
  inn: "ИНН",
  ogrn: "ОГРН",
  snils: "СНИЛС",
  bik: "БИК",
  account: "Счёт",
  passport: "Паспорт",
  secret: "Секрет (ключ, пароль)",
  address: "Адрес",
};

/**
 * Показывает найденные категории и три исхода отправки.
 *
 * @param props Состояние, находки и обработчики.
 * @returns Диалог; при `open=false` ничего не рендерит.
 */
export function CloudScanDialog({
  open,
  scan,
  busy = false,
  onCancel,
  onSendAnyway,
  onUseHybrid,
}: CloudScanDialogProps) {
  if (!scan) return null;
  const secret = scan.has_secret;
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {secret ? (
              <ShieldAlert className="text-destructive size-5" />
            ) : (
              <TriangleAlert className="text-warning size-5" />
            )}
            {secret
              ? "Похоже, в тексте есть секрет"
              : "Перед отправкой в облако"}
          </DialogTitle>
          <DialogDescription>
            Локальная проверка нашла данные, которые обычно не хотят отправлять
            внешнему провайдеру. В режиме «Облако» текст уйдёт как есть.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap gap-1">
          {scan.categories.map((item) => (
            <span
              key={item.category}
              className="bg-secondary text-secondary-foreground rounded-md px-2 py-0.5 text-pah-sm"
            >
              {CATEGORY_LABELS[item.category] ?? item.category} ×{item.count}
            </span>
          ))}
        </div>

        <Alert variant={secret ? "destructive" : "warning"}>
          <AlertDescription>
            {secret
              ? "Ключи и пароли лучше не отправлять в облако: смените режим на гибрид или удалите секрет из текста."
              : "Это предупреждение, а не блокировка: отправка возможна, но данные покинут ваш сервер."}
          </AlertDescription>
        </Alert>

        <DialogFooter className="flex-wrap gap-2">
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Отмена
          </Button>
          <Button variant="secondary" onClick={onUseHybrid} disabled={busy}>
            Перейти в гибрид
          </Button>
          <Button
            variant={secret ? "destructive" : "default"}
            onClick={onSendAnyway}
            disabled={busy}
          >
            {busy ? "Отправка…" : "Отправить как есть"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
