"use client";

// Страница «Таблицы»: анализ CSV/XLSX через песочницу DuckDB.
//
// Назначение: загрузить табличный файл (Asset), посмотреть его схему и первые
// строки, выполнить SQL-запрос и выгрузить результат в CSV/XLSX.
//
// Место в архитектуре: клиентская страница Next.js (App Router) внутри
// AppShell. Работает только через типизированный клиент `@/lib/api`:
// `api.assets`, `api.uploadAsset`, `api.tablePreview`, `api.tableQuery`.
// Браузер не обращается к внешним сервисам, а SQL исполняет backend в
// изолированном read-only окружении (enable_external_access=false).
//
// Ключевые инварианты:
// 1. SQL-запрос — только SELECT/WITH, без «;» и без DDL/DML. Это контракт
//    backend (`personal_hub.tables.validate_sql`), поэтому ограничение видно
//    пользователю заранее, а отказ приходит как стабильный код ошибки
//    (HTTP_400 от API, INVALID_TABLE_QUERY на уровне модуля) и не скрывается.
// 2. Экспорт CSV/XLSX выполняет backend
//    (`POST /api/v1/assets/{id}/table/export`): там уже есть openpyxl, поэтому
//    XLSX получается настоящим. Клиентское формирование файла дало бы лишь
//    HTML-таблицу с расширением .xls, что не является форматом XLSX.
// 3. Все классы состояний (активный файл, отображение ошибки) — статические
//    строки: Tailwind не собирает классы из интерполяции.

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useId,
  useState,
} from "react";

import { AppShell } from "@/components/app-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  ApiError,
  Asset,
  downloadBlob,
  getToken,
  setToken,
  TablePreview,
  TableQueryResult,
} from "@/lib/api";

/** Форматы выгрузки результата запроса. */
type ExportFormat = "csv" | "xlsx";

/**
 * Приводит ячейку результата к строке для отображения.
 *
 * @param value Значение из `TableQueryResult.rows` (unknown).
 * @returns Строку; `null` и `undefined` показываются как пустая строка.
 */
function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value) ?? "";
}

/** Классы элемента списка файлов: активный файл выделен фоном акцента. */
const ASSET_BUTTON_BASE =
  "w-full truncate rounded-md border px-3 py-2 text-left text-pah-sm transition-colors";
const ASSET_BUTTON_ACTIVE = `${ASSET_BUTTON_BASE} border-primary bg-accent text-accent-foreground font-medium`;
const ASSET_BUTTON_IDLE = `${ASSET_BUTTON_BASE} text-muted-foreground hover:bg-accent hover:text-accent-foreground`;

/**
 * Страница анализа таблиц.
 *
 * @returns Разметку загрузки файла, списка таблиц, предпросмотра схемы,
 *   SQL-формы и таблицы результата с выгрузкой.
 * @remarks
 * Побочные эффекты: чтение токена из localStorage, запросы к API, скачивание
 * файла выгрузки через Blob и редирект на `/login` при отсутствии токена или 401.
 */
export default function TablesPage() {
  const router = useRouter();
  // useId даёт стабильные id для связки <Label htmlFor> с полями формы;
  // он нужен, потому что id должны быть уникальны на странице и в SSR.
  const uploadId = useId();
  const sqlId = useId();
  const previewCaptionId = useId();
  const resultCaptionId = useId();

  const [assets, setAssets] = useState<Asset[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [sql, setSql] = useState("SELECT * FROM data LIMIT 20");
  const [result, setResult] = useState<TableQueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAssets(await api.assets());
    } catch (err) {
      // 401 — токен истёк или отозван: выходим из сессии (общий паттерн).
      if (
        err instanceof Error &&
        "status" in err &&
        (err as { status: number }).status === 401
      ) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка загрузки.");
      setErrorCode(err instanceof ApiError ? err.code : null);
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch на mount
    void load();
  }, [load, router]);

  /** Загружает выбранный файл и обновляет список таблиц. */
  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    if (!e.target.files?.length) return;
    setError(null);
    setErrorCode(null);
    try {
      await api.uploadAsset(e.target.files[0]);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить.");
      setErrorCode(err instanceof ApiError ? err.code : null);
    }
  }

  /** Открывает таблицу: сбрасывает прошлый результат и читает схему. */
  async function onOpen(id: string) {
    setCurrentId(id);
    setResult(null);
    setError(null);
    setErrorCode(null);
    try {
      setPreview(await api.tablePreview(id));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось открыть таблицу.",
      );
      setErrorCode(err instanceof ApiError ? err.code : null);
    }
  }

  /** Выполняет SELECT-запрос; отказ backend показывается как есть. */
  async function onQuery(e: FormEvent) {
    e.preventDefault();
    if (!currentId) return;
    setError(null);
    setErrorCode(null);
    setBusy(true);
    try {
      setResult(await api.tableQuery(currentId, sql));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка запроса.");
      setErrorCode(err instanceof ApiError ? err.code : null);
    } finally {
      setBusy(false);
    }
  }

  /**
   * Выгружает результат запроса через серверный эндпоинт экспорта.
   *
   * Файл формирует backend (`POST /assets/{id}/table/export`): там уже есть
   * openpyxl, поэтому XLSX получается настоящим, а не HTML-таблицей с
   * расширением `.xls`. Скачивание инициируется Blob-ссылкой.
   *
   * @param format Формат выгрузки: csv или xlsx.
   * @remarks Побочные эффекты: запрос к API и скачивание файла браузером.
   */
  async function onExport(format: ExportFormat) {
    if (!currentId || !sql.trim() || !result) return;
    setError(null);
    setErrorCode(null);
    try {
      const blob = await api.tableExport(currentId, sql, format);
      downloadBlob(blob, `table-export.${format}`);
    } catch (err) {
      setErrorCode(err instanceof ApiError ? err.code : null);
      setError(
        err instanceof Error ? err.message : "Не удалось выполнить экспорт.",
      );
    }
  }

  return (
    <AppShell
      title="Таблицы"
      description="Просмотр схемы CSV/XLSX и SQL-запросы в изолированной песочнице."
      actions={
        <>
          <Button variant="outline" size="sm" asChild>
            <Link href="/knowledge">Базы знаний</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/usage">Расходы</Link>
          </Button>
        </>
      }
    >
      {error && (
        <Alert variant="destructive">
          <AlertTitle>
            {errorCode ? `Ошибка: ${errorCode}` : "Ошибка"}
          </AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Загрузить CSV/XLSX</CardTitle>
          <CardDescription>
            Поддерживаются файлы .csv, .xlsx и .xls. После загрузки выберите
            таблицу в списке и выполните SQL-запрос.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Label htmlFor={uploadId}>Загрузить CSV/XLSX</Label>
          <Input
            id={uploadId}
            className="mt-2 max-w-full"
            type="file"
            onChange={onUpload}
            accept=".csv,.xlsx,.xls"
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Файлы</CardTitle>
            <CardDescription className="break-words">
              Выберите таблицу для анализа.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {loading && (
              <div role="status" aria-live="polite" aria-busy="true">
                <span className="sr-only">Загрузка списка таблиц…</span>
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="mb-2 h-9 w-full" />
                ))}
              </div>
            )}

            {!loading && assets.length === 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-pah-sm font-medium">Таблиц пока нет.</p>
                <p className="text-pah-sm text-muted-foreground">
                  Загрузите CSV или XLSX выше: файл появится в этом списке, и
                  для него станут доступны схема и SQL-запросы.
                </p>
              </div>
            )}

            {!loading &&
              assets.map((a) => {
                const isActive = currentId === a.id;
                return (
                  <button
                    key={a.id}
                    type="button"
                    aria-current={isActive ? "true" : undefined}
                    className={
                      isActive ? ASSET_BUTTON_ACTIVE : ASSET_BUTTON_IDLE
                    }
                    onClick={() => onOpen(a.id)}
                  >
                    {a.original_name}
                  </button>
                );
              })}
          </CardContent>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          {preview && (
            <Card>
              <CardHeader>
                <CardTitle>Схема ({preview.row_count} строк)</CardTitle>
                <CardDescription>
                  {preview.sample_rows.length} примеров строк ·{" "}
                  {preview.columns.length} колонок
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="w-full overflow-x-auto">
                  <table
                    className="w-full border-collapse text-pah-sm"
                    aria-describedby={previewCaptionId}
                  >
                    <caption id={previewCaptionId} className="sr-only">
                      Схема таблицы: колонки, типы и примеры строк
                    </caption>
                    <thead>
                      <tr>
                        {preview.columns.map((c) => (
                          <th
                            key={c.name}
                            scope="col"
                            className="border-b px-2 py-2 text-left align-bottom font-medium whitespace-nowrap"
                          >
                            {c.name}
                            <span className="text-muted-foreground block text-pah-xs font-normal">
                              {c.type}
                            </span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.sample_rows.map((row, i) => (
                        <tr key={i}>
                          {preview.columns.map((c, j) => (
                            <td
                              key={c.name}
                              className="border-b px-2 py-2 align-top whitespace-nowrap"
                            >
                              {cellText(row[j])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {preview && (
            <Card>
              <CardHeader>
                <CardTitle>SQL-запрос</CardTitle>
                <CardDescription>
                  Разрешены только запросы SELECT/WITH, без «;» и без DDL/DML —
                  backend отклоняет остальное.
                </CardDescription>
              </CardHeader>
              <form onSubmit={onQuery}>
                <CardContent className="flex flex-col gap-2">
                  <Label htmlFor={sqlId}>SQL-запрос</Label>
                  <Textarea
                    id={sqlId}
                    value={sql}
                    onChange={(e) => setSql(e.target.value)}
                    rows={3}
                    spellCheck={false}
                    className="font-mono"
                    placeholder="SELECT * FROM data LIMIT 20"
                  />
                </CardContent>
                <CardFooter>
                  <Button type="submit" disabled={busy}>
                    {busy ? "Выполняется…" : "Выполнить"}
                  </Button>
                </CardFooter>
              </form>
            </Card>
          )}

          {result && (
            <Card>
              <CardHeader>
                <CardTitle>Результат</CardTitle>
                <CardDescription>
                  {result.rows.length} строк · выгрузка CSV/XLSX
                </CardDescription>
              </CardHeader>
              {/* Результат приходит асинхронно: aria-live объявляет его
                  появление скринридеру без перемещения фокуса. */}
              <CardContent aria-live="polite">
                {result.rows.length === 0 && (
                  <p className="text-pah-sm text-muted-foreground mb-2">
                    Запрос выполнен, но не вернул ни одной строки.
                  </p>
                )}
                <div className="w-full overflow-x-auto">
                  <table
                    className="w-full border-collapse text-pah-sm"
                    aria-describedby={resultCaptionId}
                  >
                    <caption id={resultCaptionId} className="sr-only">
                      Результат SQL-запроса: {result.columns.length} колонок,{" "}
                      {result.rows.length} строк
                    </caption>
                    <thead>
                      <tr>
                        {result.columns.map((c) => (
                          <th
                            key={c}
                            scope="col"
                            className="border-b px-2 py-2 text-left font-medium whitespace-nowrap"
                          >
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i}>
                          {result.columns.map((c, j) => (
                            <td
                              key={c}
                              className="border-b px-2 py-2 align-top whitespace-nowrap"
                            >
                              {cellText(row[j])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
              <CardFooter className="flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={result.columns.length === 0}
                  onClick={() => onExport("csv")}
                >
                  Экспорт CSV
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={result.columns.length === 0}
                  onClick={() => onExport("xlsx")}
                >
                  Экспорт XLSX
                </Button>
                <Badge variant="secondary">
                  только SELECT · {result.rows.length} строк
                </Badge>
              </CardFooter>
            </Card>
          )}
        </div>
      </div>
    </AppShell>
  );
}
