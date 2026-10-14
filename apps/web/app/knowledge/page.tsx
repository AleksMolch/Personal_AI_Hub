"use client";

// Страница «Базы знаний»: создание базы, загрузка документов и RAG-запрос с цитатами.
//
// Назначение: дать пользователю замкнутый цикл работы со своими документами —
// создать базу знаний с моделью эмбеддингов, загрузить файлы, увидеть статус
// индексации (и её деградации по error_code) и задать вопрос, получив ответ
// строго по найденным фрагментам вместе с пронумерованными источниками.
//
// Место в архитектуре: клиентская страница Next.js (App Router) внутри
// AppShell. Работает ТОЛЬКО через типизированный клиент `@/lib/api`
// (knowledgeBases, createKnowledgeBase, getKnowledgeBase, uploadDocument,
// queryKnowledgeBase, models) и примитивы `@/components/ui/*`. Браузер не
// обращается к внешним AI-провайдерам: ключи, вызовы провайдеров и сборка
// контекста остаются на backend (apps/api/app/api/knowledge.py).
//
// Ключевые инварианты:
// 1. Цитаты — механизм доверия продукта, поэтому они не сворачиваются: каждый
//    источник показан как <figure> с заголовком документа, страницей,
//    фрагментом и оценкой релевантности. Нумерация начинается с 1 и совпадает
//    с порядком массива citations, то есть ровно с маркерами [n], которые
//    backend подставляет модели в промпт (`enumerate(citations, start=1)` в
//    `_synthesize`): ссылка [2] в тексте ответа указывает на второй источник
//    в списке ниже.
// 2. Честность ответа: `answer === null` не маскируется. Если backend вернул
//    `answer_skipped_reason` (price_missing / PRICE_REQUIRED / model_not_found /
//    provider_not_found), пользователь видит причину пропуска синтеза и сам
//    код, а сообщение «Недостаточно оснований в документах.» остаётся
//    отдельным случаем `sufficient === false`.
// 3. Деградация индексации видна: у каждого документа показываются status и,
//    если он есть, error_code (OCR_PARTIAL, PRICE_REQUIRED, PARSE_FAILED и
//    подобные) — иначе пользователь не узнает, что поиск идёт по неполным
//    данным.
// 4. Варианты Badge берутся из статических словарей-литералов: Tailwind
//    собирает классы статически, поэтому интерполяция вида `text-${status}` в
//    собранный CSS никогда не попадает.

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
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
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  Citation,
  getToken,
  KnowledgeBase,
  KnowledgeBaseDetail,
  ModelProfile,
  setToken,
} from "@/lib/api";

/** Вариант оформления бейджа: берётся из самого компонента `Badge`. */
type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>["variant"]>;

/**
 * Вариант `Badge` для статуса документа (доменный словарь backend).
 *
 * Статическая карта нужна и для типобезопасности, и для Tailwind: значения
 * перечислены литералами, поэтому классы попадают в собранный CSS.
 */
const DOC_STATUS_VARIANT: Record<string, BadgeVariant> = {
  ready: "success",
  pending: "secondary",
  processing: "secondary",
  failed: "destructive",
};

/** Русские подписи статусов документа; сам код показывается рядом. */
const DOC_STATUS_LABEL: Record<string, string> = {
  ready: "Готов",
  pending: "В очереди",
  processing: "Индексируется",
  failed: "Ошибка",
};

/**
 * Вариант `Badge` для кода ошибки документа.
 *
 * Частичная деградация (OCR_PARTIAL) и отсутствие цены (PRICE_REQUIRED) — это
 * предупреждение: данные есть, но неполные. Разбор и пустой документ — ошибка:
 * индексации не было вовсе.
 */
const DOC_ERROR_VARIANT: Record<string, BadgeVariant> = {
  OCR_PARTIAL: "warning",
  PRICE_REQUIRED: "warning",
  BUDGET_EXCEEDED: "warning",
  PARSE_FAILED: "destructive",
  EMPTY_DOCUMENT: "destructive",
  UNSUPPORTED_FORMAT: "destructive",
  OCR_FAILED: "destructive",
  INGEST_FAILED: "destructive",
};

/**
 * Пояснения к причинам пропуска синтеза ответа.
 *
 * Ключи — коды backend в snake_case (`_synthesize` возвращает price_missing,
 * model_not_found, provider_not_found) и их верхнерегистровые варианты: тот же
 * смысл приходит в `document.error_code` как PRICE_REQUIRED, а пользователю
 * важна причина, а не регистр кода.
 */
const ANSWER_SKIP_HINTS: Record<string, string> = {
  price_missing:
    "Синтез пропущен: для модели ответа не задана цена (страница «Модели»).",
  PRICE_REQUIRED:
    "Синтез пропущен: для модели ответа не задана цена (страница «Модели»).",
  model_not_found: "Синтез пропущен: выбранная модель ответа не найдена.",
  provider_not_found: "Синтез пропущен: провайдер модели ответа недоступен.",
};

/**
 * Объясняет, почему синтез ответа не состоялся.
 *
 * @param reason Код причины из `answer_skipped_reason` (значение приходит от
 *   backend и может быть неизвестным этой версии UI).
 * @returns Текст пояснения; для неизвестного кода — общая фраза, чтобы причина
 *   не исчезла из интерфейса молча (сам код показывается бейджем рядом).
 */
function skipReasonText(reason: string): string {
  return (
    ANSWER_SKIP_HINTS[reason] ??
    ANSWER_SKIP_HINTS[reason.toLowerCase()] ??
    "Синтез ответа пропущен."
  );
}

/**
 * Возвращает вариант бейджа для статуса документа.
 *
 * @param status Статус с backend (может быть новым значением, которого ещё нет
 *   в UI).
 * @returns Вариант из DOC_STATUS_VARIANT или `outline` для неизвестного статуса.
 */
function documentStatusVariant(status: string): BadgeVariant {
  return DOC_STATUS_VARIANT[status] ?? "outline";
}

/**
 * Человекочитаемая подпись статуса документа с сохранением исходного кода.
 *
 * @param status Статус документа с backend.
 * @returns Строку вида «Готов (ready)»; для неизвестного статуса — сам код,
 *   чтобы значение не потерялось.
 */
function documentStatusLabel(status: string): string {
  const label = DOC_STATUS_LABEL[status];
  return label ? `${label} (${status})` : status;
}

/**
 * Возвращает вариант бейджа для кода ошибки индексации.
 *
 * @param code Код ошибки из `document.error_code`.
 * @returns Вариант из DOC_ERROR_VARIANT; неизвестный код считается
 *   предупреждением, потому что сам факт error_code уже означает деградацию.
 */
function documentErrorVariant(code: string): BadgeVariant {
  return DOC_ERROR_VARIANT[code] ?? "warning";
}

/**
 * Проверяет, что ошибка означает истёкший или отозванный токен (HTTP 401).
 *
 * @param err Ошибка из клиента API (может быть любым значением).
 * @returns `true`, если нужно очистить токен и уйти на страницу входа.
 */
function isUnauthorized(err: unknown): boolean {
  return (
    err instanceof Error &&
    "status" in err &&
    (err as { status: number }).status === 401
  );
}

/**
 * Классы строки списка баз: активная база выделена фоном акцента.
 *
 * Это нативный `<button>`, а не Button из дизайн-системы: строка списка имеет
 * собственный вид (на всю ширину, выравнивание по левому краю) и несёт
 * `aria-current`, как список файлов на странице «Таблицы».
 */
const KB_BUTTON_BASE =
  "w-full truncate rounded-md border px-3 py-2 text-left text-pah-sm transition-colors";
const KB_BUTTON_ACTIVE = `${KB_BUTTON_BASE} border-primary bg-accent text-accent-foreground font-medium`;
const KB_BUTTON_IDLE = `${KB_BUTTON_BASE} text-muted-foreground hover:bg-accent hover:text-accent-foreground`;

/**
 * Страница баз знаний: создание базы, документы и запрос с цитатами.
 *
 * @returns Разметку трёх блоков — создание базы, список баз, выбранная база с
 *   документами и результатом запроса — внутри общей оболочки AppShell.
 * @remarks
 * Побочные эффекты: чтение токена из localStorage, запросы к API, загрузка
 * файла документа и редирект на `/login` при отсутствии токена или ответе 401.
 */
export default function KnowledgePage() {
  const router = useRouter();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [current, setCurrent] = useState<KnowledgeBaseDetail | null>(null);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [query, setQuery] = useState("");
  const [chatModel, setChatModel] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [answerSkipReason, setAnswerSkipReason] = useState<string | null>(null);
  const [citations, setCitations] = useState<Citation[]>([]);
  const [sufficient, setSufficient] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Отдельный флаг первой загрузки: по нему показывается скелетон, а не пустое
  // состояние, иначе пользователь на миг увидит «Баз пока нет».
  const [loading, setLoading] = useState(true);
  // Запрос выполняется: кнопка блокируется, чтобы не оплатить вызов дважды.
  const [busy, setBusy] = useState(false);
  // Был ли уже выполнен запрос. До него пустой список цитат означает «ещё не
  // спрашивали», а не «ничего не найдено».
  const [queried, setQueried] = useState(false);

  // Стабильные id для связки Label ↔ поле и для заголовков-ориентиров.
  const createTitleId = useId();
  const nameId = useId();
  const embeddingModelId = useId();
  const listTitleId = useId();
  const currentTitleId = useId();
  const uploadId = useId();
  const queryId = useId();
  const chatModelId = useId();
  const resultTitleId = useId();

  // Ссылки на формы нужны действиям пустых состояний: фокус сам прокручивает
  // страницу к нужному полю, поэтому отдельный scrollIntoView не требуется.
  const createFormRef = useRef<HTMLFormElement>(null);
  const documentsRef = useRef<HTMLDivElement>(null);
  const queryFormRef = useRef<HTMLFormElement>(null);

  const load = useCallback(async () => {
    try {
      const [k, m] = await Promise.all([api.knowledgeBases(), api.models()]);
      setKbs(k);
      setModels(m);
      // Первая модель выбирается по умолчанию и для эмбеддингов, и для ответа:
      // так запрос можно выполнить сразу после создания базы.
      if (m.length > 0) {
        setModelId(m[0].id);
        setChatModel(m[0].id);
      }
    } catch (err) {
      // 401 — токен истёк: чистим его и уводим на вход, а не показываем ошибку.
      if (isUnauthorized(err)) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка загрузки.");
    } finally {
      // Скелетон снимается в любом случае, иначе ошибка оставила бы его навсегда.
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

  /**
   * Создаёт базу знаний.
   *
   * Пустое название заменяется на «База знаний»: backend не принимает пустое
   * имя, а пользователь не обязан вводить его вручную.
   *
   * @param e Событие отправки формы создания.
   */
  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createKnowledgeBase(name || "База знаний", modelId);
      setName("");
      await load();
    } catch (err) {
      if (isUnauthorized(err)) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Не удалось создать.");
    }
  }

  /**
   * Открывает базу знаний и сбрасывает результат прошлого запроса.
   *
   * Сброс обязателен: чужие цитаты в контексте новой базы выглядели бы как
   * источники из неё.
   *
   * @param id Идентификатор базы знаний.
   */
  async function onOpen(id: string) {
    setError(null);
    setCitations([]);
    setAnswer(null);
    setAnswerSkipReason(null);
    // Исходное состояние: оснований достаточно, вопрос ещё не задавали.
    setSufficient(true);
    setQueried(false);
    try {
      setCurrent(await api.getKnowledgeBase(id));
    } catch (err) {
      if (isUnauthorized(err)) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Не удалось открыть базу.");
    }
  }

  /**
   * Загружает документ в открытую базу и перечитывает её состояние.
   *
   * Индексация асинхронная: ответ API содержит только document_id и job_id,
   * поэтому статус документа пока берётся повторным чтением базы (pending),
   * а не из ответа загрузки.
   *
   * @param e Событие выбора файла.
   */
  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    if (!current || !e.target.files?.length) return;
    setError(null);
    try {
      await api.uploadDocument(current.id, e.target.files[0]);
      setCurrent(await api.getKnowledgeBase(current.id));
    } catch (err) {
      if (isUnauthorized(err)) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(
        err instanceof Error ? err.message : "Не удалось загрузить документ.",
      );
    }
  }

  /**
   * Выполняет RAG-запрос по открытой базе.
   *
   * top_k фиксирован (5): столько фрагментов уходит в контекст синтеза, и
   * столько же источников максимум увидит пользователь.
   *
   * @param e Событие отправки формы запроса.
   */
  async function onQuery(e: FormEvent) {
    e.preventDefault();
    if (!current || !query.trim()) return;
    setError(null);
    setBusy(true);
    try {
      const result = await api.queryKnowledgeBase(
        current.id,
        query.trim(),
        5,
        chatModel || undefined,
      );
      setCitations(result.citations);
      setSufficient(result.sufficient);
      setAnswer(result.answer);
      setAnswerSkipReason(result.answer_skipped_reason ?? null);
      setQueried(true);
    } catch (err) {
      if (isUnauthorized(err)) {
        setToken(null);
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка запроса.");
    } finally {
      setBusy(false);
    }
  }

  /** Переводит фокус в поле названия — действие пустого состояния «Мои базы». */
  function focusCreateForm() {
    createFormRef.current
      ?.querySelector<HTMLElement>("[data-slot='input']")
      ?.focus();
  }

  /** Переводит фокус к выбору файла — действие пустого состояния документов. */
  function focusDocumentUpload() {
    documentsRef.current
      ?.querySelector<HTMLElement>("[data-slot='input']")
      ?.focus();
  }

  /** Переводит фокус в поле вопроса — действие пустого состояния источников. */
  function focusQueryField() {
    queryFormRef.current
      ?.querySelector<HTMLElement>("[data-slot='input']")
      ?.focus();
  }

  return (
    <AppShell
      title="Базы знаний"
      description="Загрузка документов, индексация и ответы строго по найденным фрагментам — с цитатами."
      actions={
        <>
          <Button variant="outline" size="sm" asChild>
            <Link href="/chat">Чат</Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/jobs">Задачи</Link>
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        {/* Ошибка загрузки или действия: Alert уже имеет role="alert". */}
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Ошибка</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Первая загрузка: показываем структуру экрана, чтобы не было «прыжка». */}
        {loading && (
          <div
            role="status"
            aria-live="polite"
            aria-busy="true"
            className="flex flex-col gap-4"
          >
            <span className="sr-only">Загрузка списка баз…</span>
            {[0, 1].map((i) => (
              <Card key={i}>
                <CardHeader>
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-4 w-56" />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Skeleton className="h-9 w-full" />
                  <Skeleton className="h-9 w-2/3" />
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {!loading && (
          <>
            <section
              aria-labelledby={createTitleId}
              className="flex flex-col gap-3"
            >
              <div className="flex flex-col gap-1">
                <h2
                  id={createTitleId}
                  className="text-pah-xl font-semibold tracking-tight"
                >
                  Создать базу знаний
                </h2>
                <p className="text-muted-foreground text-pah-sm">
                  Выберите модель эмбеддингов: ею будут векторизованы документы
                  базы, и от неё зависит векторный индекс.
                </p>
              </div>

              <Card>
                <CardContent>
                  <form
                    ref={createFormRef}
                    onSubmit={onCreate}
                    className="flex flex-col gap-4"
                  >
                    <div className="flex flex-col gap-2">
                      <Label htmlFor={nameId}>Название</Label>
                      <Input
                        id={nameId}
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Название"
                      />
                    </div>

                    <div className="flex flex-col gap-2">
                      <Label htmlFor={embeddingModelId}>
                        Модель для эмбеддингов
                      </Label>
                      <Select value={modelId} onValueChange={setModelId}>
                        <SelectTrigger
                          id={embeddingModelId}
                          className="w-full"
                          aria-label="Модель для эмбеддингов"
                        >
                          <SelectValue placeholder="Модель не выбрана" />
                        </SelectTrigger>
                        <SelectContent>
                          {models.map((m) => (
                            <SelectItem key={m.id} value={m.id}>
                              {m.display_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <Button type="submit">Создать</Button>
                    </div>
                  </form>
                </CardContent>
              </Card>
            </section>

            <section
              aria-labelledby={listTitleId}
              aria-live="polite"
              className="flex flex-col gap-3"
            >
              <h2
                id={listTitleId}
                className="text-pah-xl font-semibold tracking-tight"
              >
                Мои базы
              </h2>

              {kbs.length === 0 ? (
                <Card>
                  <CardHeader>
                    <CardTitle>Баз пока нет.</CardTitle>
                    <CardDescription>
                      Создайте базу знаний выше: в неё загружаются документы, по
                      которым затем строятся ответы с цитатами.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={focusCreateForm}
                    >
                      Создать базу
                    </Button>
                  </CardContent>
                </Card>
              ) : (
                <ul className="flex flex-col gap-2">
                  {kbs.map((kb) => {
                    const isActive = current?.id === kb.id;
                    return (
                      <li key={kb.id}>
                        <button
                          type="button"
                          aria-current={isActive ? "true" : undefined}
                          className={
                            isActive ? KB_BUTTON_ACTIVE : KB_BUTTON_IDLE
                          }
                          onClick={() => void onOpen(kb.id)}
                        >
                          {kb.name}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>

            {current && (
              <section
                aria-labelledby={currentTitleId}
                className="flex flex-col gap-4"
              >
                <div className="flex flex-col gap-1">
                  <h2
                    id={currentTitleId}
                    className="text-pah-xl font-semibold tracking-tight"
                  >
                    Текущая база
                  </h2>
                  {/* Имя базы — пользовательские данные, поэтому это не
                      заголовок: на странице обязан остаться ровно один
                      заголовок верхнего уровня (его проверяет E2E-тест). */}
                  <p className="text-pah-lg font-medium break-words">
                    {current.name}
                  </p>
                </div>

                <Card>
                  <CardHeader>
                    <CardTitle>Документы:</CardTitle>
                    <CardDescription>
                      Файл обрабатывается в фоне: статус и код ошибки
                      показывают, прошла ли индексация полностью.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-4">
                    <div ref={documentsRef} className="flex flex-col gap-2">
                      <Label htmlFor={uploadId}>Загрузить документ</Label>
                      {/* Список accept повторяет форматы парсера backend: */}
                      {/* текст, PDF, DOCX и изображения для OCR. */}
                      <Input
                        id={uploadId}
                        className="max-w-full"
                        type="file"
                        onChange={onUpload}
                        accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.tif,.tiff,.webp,.bmp"
                      />
                    </div>

                    {current.documents.length === 0 ? (
                      <Card className="bg-muted/30">
                        <CardHeader>
                          <CardTitle className="text-pah-base">
                            Документов пока нет.
                          </CardTitle>
                          <CardDescription>
                            Выберите файл выше — после индексации он появится в
                            списке со статусом и, при сбое, с кодом ошибки.
                          </CardDescription>
                        </CardHeader>
                        <CardContent>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={focusDocumentUpload}
                          >
                            Выбрать файл
                          </Button>
                        </CardContent>
                      </Card>
                    ) : (
                      <ul className="flex flex-col">
                        {current.documents.map((d) => (
                          <li
                            key={d.id}
                            className="flex flex-col gap-2 border-b py-3 last:border-b-0"
                          >
                            <span className="text-pah-sm font-medium break-words">
                              {d.title}
                            </span>
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant={documentStatusVariant(d.status)}>
                                {documentStatusLabel(d.status)}
                              </Badge>
                              {/* error_code — единственный сигнал о деградации
                                  индексации, поэтому он показывается всегда,
                                  когда пришёл с backend. */}
                              {d.error_code && (
                                <Badge
                                  variant={documentErrorVariant(d.error_code)}
                                >
                                  {d.error_code}
                                </Badge>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Запрос по документам</CardTitle>
                    <CardDescription>
                      Ответ строится только по найденным фрагментам; ссылки вида
                      [1] в ответе соответствуют номерам источников ниже.
                    </CardDescription>
                  </CardHeader>
                  <form ref={queryFormRef} onSubmit={onQuery}>
                    <CardContent className="flex flex-col gap-4">
                      <div className="flex flex-col gap-2">
                        <Label htmlFor={queryId}>Вопрос</Label>
                        <Input
                          id={queryId}
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          placeholder="Задайте вопрос по документам…"
                        />
                      </div>

                      <div className="flex flex-col gap-2">
                        <Label htmlFor={chatModelId}>Модель ответа</Label>
                        <Select value={chatModel} onValueChange={setChatModel}>
                          <SelectTrigger
                            id={chatModelId}
                            className="w-full"
                            aria-label="Модель ответа"
                          >
                            <SelectValue placeholder="Модель не выбрана" />
                          </SelectTrigger>
                          <SelectContent>
                            {models.map((m) => (
                              <SelectItem key={m.id} value={m.id}>
                                {m.display_name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </CardContent>
                    <div className="flex items-center px-4">
                      <Button type="submit" disabled={busy || !query.trim()}>
                        {busy ? "Спрашиваем…" : "Спросить"}
                      </Button>
                    </div>
                  </form>
                </Card>

                {/* Результат приходит асинхронно: aria-live объявляет его
                    появление скринридеру, не перемещая фокус. */}
                <section
                  aria-labelledby={resultTitleId}
                  aria-live="polite"
                  aria-busy={busy}
                  className="flex flex-col gap-3"
                >
                  <h3
                    id={resultTitleId}
                    className="text-pah-lg font-semibold tracking-tight"
                  >
                    Результат запроса
                  </h3>

                  {busy && (
                    <p className="text-muted-foreground text-pah-sm">
                      Идёт поиск по документам…
                    </p>
                  )}

                  {!queried && !busy && (
                    <p className="text-muted-foreground text-pah-sm">
                      Задайте вопрос — здесь появятся ответ и пронумерованные
                      источники.
                    </p>
                  )}

                  {answer && (
                    <Card>
                      <CardHeader>
                        <CardTitle>Ответ</CardTitle>
                      </CardHeader>
                      <CardContent>
                        {/* whitespace-pre-wrap сохраняет абзацы модели. */}
                        <p className="text-pah-base leading-relaxed break-words whitespace-pre-wrap">
                          {answer}
                        </p>
                      </CardContent>
                    </Card>
                  )}

                  {/* Причина пропуска синтеза: answer === null, но backend
                      объяснил, почему ответ не был построен. */}
                  {!answer && answerSkipReason && (
                    <Alert variant="info">
                      <AlertTitle>Синтез ответа пропущен</AlertTitle>
                      <AlertDescription>
                        <p>{skipReasonText(answerSkipReason)}</p>
                        <Badge variant="outline">{answerSkipReason}</Badge>
                      </AlertDescription>
                    </Alert>
                  )}

                  {/* Причина не пришла, потому что синтез и не запрашивался:
                      модель ответа не выбрана. */}
                  {answer === null &&
                    !answerSkipReason &&
                    sufficient &&
                    queried && (
                      <Alert variant="info">
                        <AlertTitle>Синтез ответа не выполнялся</AlertTitle>
                        <AlertDescription>
                          Выберите модель ответа — без неё backend возвращает
                          только найденные фрагменты.
                        </AlertDescription>
                      </Alert>
                    )}

                  {!sufficient && (
                    <Alert variant="warning">
                      <AlertDescription>
                        Недостаточно оснований в документах.
                      </AlertDescription>
                    </Alert>
                  )}

                  {citations.length > 0 && (
                    <div className="flex flex-col gap-3">
                      <h4 className="text-pah-base font-semibold">Источники</h4>
                      {/* Нумерованный список: номер совпадает с маркером [n],
                          который backend просит использовать в ответе. */}
                      <ol className="flex flex-col gap-3">
                        {citations.map((c, index) => (
                          <li key={c.chunk_id}>
                            <figure className="bg-card flex flex-col gap-2 rounded-lg border p-3 sm:p-4">
                              <figcaption className="flex flex-wrap items-center gap-2 text-pah-sm">
                                <span className="text-primary font-semibold tabular-nums">
                                  [{index + 1}]
                                </span>
                                <span className="font-medium break-words">
                                  {c.document_title}
                                </span>
                                {c.page ? (
                                  <span className="text-muted-foreground">
                                    стр. {c.page}
                                  </span>
                                ) : null}
                                {/* Оценка релевантности объясняет, почему
                                    фрагмент попал в контекст. */}
                                <Badge
                                  variant="secondary"
                                  className="tabular-nums"
                                >
                                  релевантность {c.score.toFixed(2)}
                                </Badge>
                              </figcaption>
                              <blockquote className="text-muted-foreground border-l-2 pl-3 text-pah-sm break-words whitespace-pre-wrap">
                                {c.text}
                              </blockquote>
                            </figure>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}

                  {queried && citations.length === 0 && (
                    <Card>
                      <CardHeader>
                        <CardTitle>Источники не найдены.</CardTitle>
                        <CardDescription>
                          Ни один фрагмент документов не прошёл порог
                          релевантности. Проверьте, что документы
                          проиндексированы (статус «Готов»), и переформулируйте
                          вопрос.
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={focusQueryField}
                        >
                          Изменить вопрос
                        </Button>
                      </CardContent>
                    </Card>
                  )}
                </section>
              </section>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
