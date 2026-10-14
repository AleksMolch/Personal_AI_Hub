"use client";

// Страница «Провайдеры» — подключение и обслуживание внешних LLM-провайдеров.
//
// Назначение: выбор пресета, добавление OpenAI-совместимого провайдера с
// API-ключом, проверка соединения, синхронизация каталога моделей и удаление
// провайдера. Это первый экран после входа, поэтому пустое состояние обязано
// подсказывать пользователю первое действие.
//
// Основные сущности: компонент ProvidersPage (единственный экспорт), локальные
// состояния формы добавления и карточек провайдеров; типы Provider и Preset и
// методы api.* берутся из @/lib/api.
//
// Место в архитектуре: клиентская страница Next.js (App Router, сегмент
// /providers). Оболочка AppShell даёт общую навигацию и заголовок h1
// «Провайдеры», который рендерится сразу, не дожидаясь данных: тело страницы
// подгружается отдельно (скелет), а E2E-тест проверяет заголовок немедленно
// после входа. UI не обращается к AI-провайдерам напрямую — только к своему
// backend.
//
// Зависимости: @/components/app-shell, примитивы @/components/ui/*,
// @/lib/api (Provider, Preset, api.providers/presets/createProvider/
// testProvider/syncModels/deleteProvider).
//
// Инварианты безопасности (нарушать нельзя):
// 1. Backend никогда не возвращает ключ — в ответе Provider есть только маска
//    key_mask. Страница показывает исключительно маску.
// 2. Новый ключ вводится в поле type="password", хранится в состоянии ровно до
//    успешного создания провайдера и сразу очищается.
// 3. Ключ не попадает в разметку, DOM-атрибуты, URL, console.* и тексты ошибок.
// 4. Переключателя «показать ключ» нет намеренно.

import {
  FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app-shell";
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
import { PrivacyBadge } from "@/components/ui/privacy-badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, getToken, Provider, Preset, setToken } from "@/lib/api";

/** Сколько скелетов-карточек показывать при первой загрузке списка. */
const SKELETON_ROWS = [0, 1];

/**
 * Распознаёт отказ авторизации (401) в ошибке, пришедшей из api.*.
 *
 * Проверка идёт по полю status, а не по тексту сообщения: текст локализован
 * backend'ом и не является стабильным признаком.
 *
 * @param err Любое значение, пойманное в catch.
 * @returns true, если ошибка означает истёкшую или отсутствующую сессию.
 */
function isUnauthorized(err: unknown): boolean {
  return (
    err instanceof Error &&
    "status" in err &&
    (err as { status: number }).status === 401
  );
}

/**
 * Страница управления провайдерами.
 *
 * Побочные эффекты: запросы к backend через api.*; при 401 сбрасывает токен и
 * переводит пользователя на /login; отправляет API-ключ один раз при создании
 * провайдера и очищает поле после успеха.
 *
 * @returns Разметку страницы внутри общей оболочки AppShell.
 */
export default function ProvidersPage() {
  const router = useRouter();
  // Идентификаторы для связи <Label htmlFor> с полями формы (a11y).
  const presetFieldId = useId();
  const nameFieldId = useId();
  const baseUrlFieldId = useId();
  const apiKeyFieldId = useId();
  const formRef = useRef<HTMLFormElement>(null);

  const [providers, setProviders] = useState<Provider[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  /** Признак «идёт запрос» по id провайдера: защищает от двойных нажатий. */
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const [providerType, setProviderType] = useState("openai_compatible");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  // В состоянии лежит только то, что пользователь ещё не отправил. После
  // успешного создания ключ стирается и больше нигде не хранится.
  const [apiKey, setApiKey] = useState("");
  const [testMsg, setTestMsg] = useState<Record<string, string>>({});

  /**
   * Единый шаблон обработки 401: сброс токена и переход на страницу входа.
   *
   * @param err Ошибка, полученная от api.*.
   * @returns true, если выполнен переход на /login — вызывающий код должен
   *   прекратить обработку, чтобы не показывать пользователю технический текст.
   */
  const redirectIfUnauthorized = useCallback(
    (err: unknown): boolean => {
      if (!isUnauthorized(err)) return false;
      setToken(null);
      router.push("/login");
      return true;
    },
    [router],
  );

  /** Загружает список провайдеров и пресеты (валюту и Base URL формы). */
  const load = useCallback(async () => {
    try {
      const [providerList, presetList] = await Promise.all([
        api.providers(),
        api.presets(),
      ]);
      setProviders(providerList);
      setPresets(presetList);
    } catch (err) {
      if (redirectIfUnauthorized(err)) return;
      setError(err instanceof Error ? err.message : "Ошибка загрузки.");
    } finally {
      setLoading(false);
    }
  }, [redirectIfUnauthorized]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    void load();
  }, [load, router]);

  /**
   * Переключение пресета: запоминает тип провайдера и подставляет Base URL.
   *
   * Валюта здесь не хранится отдельным состоянием — она берётся из пресета в
   * момент создания провайдера (как и раньше).
   */
  function onPresetChange(type: string) {
    setProviderType(type);
    const preset = presets.find((p) => p.provider_type === type);
    if (preset) setBaseUrl(preset.base_url);
  }

  /** Добавляет провайдера и очищает введённый ключ после успеха. */
  async function onAdd(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.createProvider({
        provider_type: providerType,
        display_name: displayName || providerType,
        base_url: baseUrl,
        api_key: apiKey,
        currency:
          presets.find((p) => p.provider_type === providerType)?.currency ??
          "USD",
      });
      setDisplayName("");
      // Ключ зашифрован на backend и обратно не приходит — держать его в
      // памяти браузера дальше не нужно.
      setApiKey("");
      await load();
    } catch (err) {
      // Ключ намеренно не очищаем: пользователь может повторить попытку, не
      // вводя его заново. Текст ошибки приходит с backend и ключ не содержит.
      if (redirectIfUnauthorized(err)) return;
      setError(
        err instanceof Error ? err.message : "Не удалось добавить провайдера.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  /**
   * Проверяет соединение с провайдером.
   *
   * Результат пишется в живой регион карточки (aria-live="polite"), поэтому
   * скринридер объявляет его без перемещения фокуса.
   */
  async function onTest(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    setTestMsg((m) => ({ ...m, [id]: "Проверка…" }));
    try {
      const r = await api.testProvider(id);
      setTestMsg((m) => ({ ...m, [id]: r.message }));
    } catch (err) {
      if (redirectIfUnauthorized(err)) return;
      setTestMsg((m) => ({
        ...m,
        [id]: err instanceof Error ? err.message : "Ошибка",
      }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  /** Синхронизирует каталог моделей провайдера с удалённым списком. */
  async function onSync(id: string) {
    setBusy((b) => ({ ...b, [id]: true }));
    setTestMsg((m) => ({ ...m, [id]: "Синхронизация…" }));
    try {
      const models = await api.syncModels(id);
      setTestMsg((m) => ({ ...m, [id]: `Моделей: ${models.length}` }));
    } catch (err) {
      if (redirectIfUnauthorized(err)) return;
      setTestMsg((m) => ({
        ...m,
        [id]: err instanceof Error ? err.message : "Ошибка",
      }));
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  /**
   * Удаляет провайдера и обновляет список.
   *
   * Подтверждения нет намеренно: оно не входило в исходное поведение, а ключ
   * после удаления не восстанавливается — провайдера можно добавить заново.
   */
  async function onDelete(id: string) {
    setError(null);
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      await api.deleteProvider(id);
      await load();
    } catch (err) {
      if (redirectIfUnauthorized(err)) return;
      setError(
        err instanceof Error ? err.message : "Не удалось удалить провайдера.",
      );
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }

  /**
   * Переводит фокус на первое поле формы добавления.
   *
   * Нужно кнопке пустого состояния: фокус сам прокручивает страницу к форме,
   * поэтому отдельный scrollIntoView не требуется.
   */
  function focusAddForm() {
    formRef.current
      ?.querySelector<HTMLElement>("[data-slot='select-trigger']")
      ?.focus();
  }

  return (
    <AppShell
      title="Провайдеры"
      description="Ключи шифруются на сервере; в интерфейсе показывается только маска."
    >
      <div className="flex flex-col gap-6">
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Добавить провайдера</CardTitle>
            <CardDescription>
              Выберите пресет, проверьте Base URL и вставьте API-ключ. Ключ
              отправляется на сервер один раз и обратно не возвращается.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              ref={formRef}
              onSubmit={onAdd}
              className="flex flex-col gap-4"
            >
              <div className="flex flex-col gap-2">
                <Label htmlFor={presetFieldId}>Пресет</Label>
                <Select value={providerType} onValueChange={onPresetChange}>
                  <SelectTrigger id={presetFieldId} className="w-full">
                    <SelectValue placeholder="Выберите пресет" />
                  </SelectTrigger>
                  <SelectContent>
                    {presets.map((p) => (
                      <SelectItem key={p.provider_type} value={p.provider_type}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor={nameFieldId}>Название</Label>
                <Input
                  id={nameFieldId}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Мой провайдер"
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor={baseUrlFieldId}>Base URL</Label>
                <Input
                  id={baseUrlFieldId}
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://api.example.com/v1"
                  required
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor={apiKeyFieldId}>API-ключ</Label>
                {/* type="password" не даёт ключу попасть в текст DOM, а
                    autoComplete="off" — в менеджер паролей браузера. */}
                <Input
                  id={apiKeyFieldId}
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  required
                />
              </div>

              <div>
                <Button type="submit" disabled={submitting}>
                  Добавить
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <section
          className="flex flex-col gap-4"
          aria-labelledby="providers-list-title"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2
              id="providers-list-title"
              className="text-pah-xl font-semibold tracking-tight"
            >
              Подключённые
            </h2>
            {/* Все провайдеры на этой странице внешние: запрос уходит в облако и
                оплачивается ключом пользователя (локального inference нет). */}
            <PrivacyBadge mode="cloud" size="sm" />
          </div>

          {loading && (
            <div className="flex flex-col gap-4" aria-busy="true">
              <p className="text-muted-foreground text-sm">Загрузка…</p>
              {SKELETON_ROWS.map((row) => (
                <Card key={row} aria-hidden="true">
                  <CardHeader>
                    <Skeleton className="h-5 w-40 max-w-full" />
                    <Skeleton className="h-3.5 w-56 max-w-full" />
                    <Skeleton className="h-3 w-72 max-w-full" />
                  </CardHeader>
                  <CardContent className="flex flex-wrap gap-2">
                    <Skeleton className="h-8 w-24" />
                    <Skeleton className="h-8 w-32" />
                    <Skeleton className="h-8 w-20" />
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {!loading && providers.length === 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Ещё ничего не подключено</CardTitle>
                <CardDescription>Пока нет провайдеров.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <p className="text-muted-foreground text-sm">
                  Добавьте OpenAI-совместимого провайдера, чтобы работать с
                  моделями: выберите пресет (OpenRouter, RouterAI, Selectel и
                  другие), проверьте Base URL и вставьте API-ключ. Ключ
                  шифруется на сервере, здесь останется только маска.
                </p>
                <div>
                  <Button onClick={focusAddForm}>
                    Добавить первого провайдера
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {providers.map((p) => (
            <Card key={p.id}>
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle>{p.display_name}</CardTitle>
                    {/* Только маска ключа, полученная с backend: полного
                        ключа нет ни в ответе API, ни в разметке. */}
                    <CardDescription className="mt-1">
                      {p.provider_type} · ключ {p.key_mask}
                    </CardDescription>
                    <div className="text-muted-foreground mt-1 font-mono text-pah-xs break-all">
                      {p.base_url}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void onTest(p.id)}
                      disabled={busy[p.id] === true}
                    >
                      Проверить
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void onSync(p.id)}
                      disabled={busy[p.id] === true}
                    >
                      Синхронизировать
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => void onDelete(p.id)}
                      disabled={busy[p.id] === true}
                    >
                      Удалить
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {/* Живой регион отрисован всегда, даже пустым: скринридер
                    объявляет обновление только у контейнера aria-live, который
                    уже существовал в DOM до изменения текста. */}
                <p
                  className="text-muted-foreground min-h-5 text-sm"
                  role="status"
                  aria-live="polite"
                >
                  {testMsg[p.id] ?? ""}
                </p>
              </CardContent>
            </Card>
          ))}
        </section>
      </div>
    </AppShell>
  );
}
