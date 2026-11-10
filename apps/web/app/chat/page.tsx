"use client";

// Страница чата: диалоги, потоковый ответ и экономические индикаторы.
//
// Назначение: основной пользовательский сценарий — вести диалог с выбранной
// моделью, видеть потоковый ответ, останавливать генерацию и понимать
// стоимость каждого ответа. Здесь сходятся три ключевые ценности продукта:
// контроль расходов, прозрачность обработки и работа со своим API-ключом.
//
// Место в архитектуре: страница-оркестратор. Она владеет состоянием диалога,
// подписывается на SSE-поток генерации (`/generations/{id}/events`) и
// обогащает сообщения данными расходов из `/usage/records`. Презентация
// вынесена в компоненты `components/chat/*`.
//
// Важно: браузер не обращается к внешним AI-провайдерам напрямую — только к
// собственному backend, который владеет ключами и вызывает провайдеров.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Menu, Plus, Search } from "lucide-react";

import {
  ChatInput,
  type ChatInputModel,
  type ReasoningDepth,
} from "@/components/chat/chat-input";
import { EmptyChatState } from "@/components/chat/empty-chat-state";
import { MessageList } from "@/components/chat/message-list";
import type { ChatMessageView } from "@/components/chat/message";
import type { WebSource } from "@/components/chat/web-sources";
import { NavigationLinks } from "@/components/navigation-links";
import { PageHeading } from "@/components/page-heading";
import { ThemeToggle } from "@/components/theme-toggle";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  Conversation,
  eventSourceUrl,
  getToken,
  Message,
  ModelProfile,
  ProtectionPreview,
  setToken,
  UsageRecord,
  UsageSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Примеры запросов для пустого состояния. */
const EXAMPLE_PROMPTS = [
  "Объясни разницу между RAG и дообучением модели",
  "Составь план проверки бюджета на месяц",
  "Помоги сформулировать письмо клиенту",
];

/**
 * Режимы обработки данных теперь выбираются внутри композера
 * (`components/chat/chat-input.tsx`), поэтому дублирующий список здесь не нужен.
 */

/**
 * Страница чата.
 *
 * @returns Раскладку из списка диалогов и области переписки.
 */
export default function ChatPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [usageByMessage, setUsageByMessage] = useState<
    Record<string, UsageRecord>
  >({});
  const esRef = useRef<EventSource | null>(null);
  const [draft, setDraft] = useState("");
  // Возможности сервера: переключатель веб-доступа рендерится только если
  // веб-поиск действительно включён (WEB_SEARCH_ENABLED=1).
  const [webSearchAvailable, setWebSearchAvailable] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  // Защищённые режимы (ADR-0007): переключатель показывается только когда
  // сервер подтвердил готовность, а не по одному факту наличия кода.
  const [protectionAvailable, setProtectionAvailable] = useState(false);
  const [protectionMode, setProtectionMode] =
    useState<string>("cloud_controlled");
  // Preview подготовки: показывается до отправки, пока пользователь не
  // подтвердит именно этот sanitized-текст.
  const [protectionPreview, setProtectionPreview] =
    useState<ProtectionPreview | null>(null);
  const [pendingSend, setPendingSend] = useState<{
    conversationId: string;
    text: string;
    options: { reasoningDepth?: ReasoningDepth };
  } | null>(null);
  const [protectionBusy, setProtectionBusy] = useState(false);

  /**
   * Загружает диалоги, модели, сводку расходов и записи usage.
   * Стоимость каждого ответа берётся из usage по `message_id`.
   */
  const loadAll = useCallback(async () => {
    try {
      const [c, m, s, records, caps] = await Promise.all([
        api.conversations(),
        api.models(),
        api.usageSummary().catch(() => null),
        api.usageRecords().catch(() => [] as UsageRecord[]),
        api
          .capabilities()
          .catch(() => ({ web_search: false, protection: undefined })),
      ]);
      setConversations(c);
      setModels(m);
      setSummary(s);
      setWebSearchAvailable(caps.web_search);
      setProtectionAvailable(Boolean(caps.protection?.enabled));
      const byMessage: Record<string, UsageRecord> = {};
      for (const record of records) {
        if (record.message_id) byMessage[record.message_id] = record;
      }
      setUsageByMessage(byMessage);
      if (m.length > 0) setSelectedModel((prev) => prev || m[0].id);

      if (c.length > 0) {
        setCurrentId(c[0].id);
        const detail = await api.getConversation(c[0].id);
        setMessages(detail.messages);
        setProtectionMode(detail.protection_mode);
      }
    } catch {
      setError("Не удалось загрузить данные.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch на mount
    void loadAll();
    return () => esRef.current?.close();
  }, [loadAll, router]);

  /** Открывает диалог и загружает его сообщения. */
  async function openConversation(id: string) {
    setCurrentId(id);
    setSidebarOpen(false);
    setError(null);
    try {
      const detail = await api.getConversation(id);
      setMessages(detail.messages);
      setProtectionMode(detail.protection_mode);
    } catch {
      setError("Не удалось открыть диалог.");
    }
  }

  /** Создаёт новый пустой диалог. */
  async function newConversation() {
    try {
      const conv = await api.createConversation({ title: "Новый диалог" });
      setConversations((c) => [conv, ...c]);
      setCurrentId(conv.id);
      setMessages([]);
      setSidebarOpen(false);
      setError(null);
    } catch {
      setError("Не удалось создать диалог.");
    }
  }

  /** Прерывает поток и просит backend отменить генерацию. */
  function stopStreaming() {
    esRef.current?.close();
    setStreaming(false);
    if (streamingId) {
      api.cancelGeneration(streamingId).catch(() => undefined);
    }
    void refreshCurrent();
  }

  /** Перечитывает сообщения текущего диалога и расходы после генерации. */
  async function refreshCurrent() {
    if (currentId) {
      try {
        const detail = await api.getConversation(currentId);
        setMessages(detail.messages);
        const records = await api
          .usageRecords()
          .catch(() => [] as UsageRecord[]);
        const byMessage: Record<string, UsageRecord> = {};
        for (const record of records) {
          if (record.message_id) byMessage[record.message_id] = record;
        }
        setUsageByMessage(byMessage);
        setSummary(await api.usageSummary().catch(() => null));
      } catch {
        // Отображать ошибку здесь не нужно: история уже видна пользователю.
      }
    }
    setStreamContent("");
  }

  /**
   * Отправляет сообщение и открывает SSE-поток генерации.
   *
   * @param content Текст сообщения.
   * @param options Параметры запроса (глубина рассуждений).
   */
  /** Возвращает id диалога, создавая его лениво при первом сообщении. */
  async function ensureConversation(): Promise<string | null> {
    if (currentId) return currentId;
    try {
      const conv = await api.createConversation({ title: "Новый диалог" });
      setConversations((c) => [conv, ...c]);
      setCurrentId(conv.id);
      // Выбранный до создания режим применяем сразу: иначе первое сообщение
      // ушло бы в облако, хотя пользователь выбрал гибрид.
      if (protectionAvailable && protectionMode !== "cloud_controlled") {
        await api.setProtectionMode(conv.id, protectionMode);
      }
      return conv.id;
    } catch {
      setError("Не удалось создать диалог.");
      return null;
    }
  }

  /**
   * Отправляет сообщение: в гибриде сначала готовит preview, иначе сразу.
   *
   * @param content Текст сообщения.
   * @param options Параметры запроса (глубина рассуждений).
   */
  async function send(
    content: string,
    options: { reasoningDepth?: ReasoningDepth } = {},
  ) {
    const text = content.trim();
    if (!text || streaming) return;
    setError(null);

    const conversationId = await ensureConversation();
    if (!conversationId) return;

    // В гибриде отправка без подтверждённого preview запрещена сервером:
    // показываем пользователю, что именно уйдёт модели.
    if (protectionAvailable && protectionMode === "protected_hybrid") {
      setProtectionBusy(true);
      try {
        const preview = await api.prepareProtection(conversationId, text);
        setProtectionPreview(preview);
        setPendingSend({ conversationId, text, options });
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось подготовить защищённый запрос.",
        );
      } finally {
        setProtectionBusy(false);
      }
      return;
    }

    await deliver(conversationId, text, options);
  }

  /** Подтверждает preview и отправляет именно тот sanitized-текст. */
  async function confirmProtection() {
    if (!protectionPreview || !pendingSend) return;
    setProtectionBusy(true);
    try {
      await api.commitProtection(pendingSend.conversationId, {
        preparation_id: protectionPreview.preparation_id,
        digest: protectionPreview.digest,
        revision: protectionPreview.revision,
      });
      const { preparation_id } = protectionPreview;
      const pending = pendingSend;
      setProtectionPreview(null);
      setPendingSend(null);
      await deliver(
        pending.conversationId,
        pending.text,
        pending.options,
        preparation_id,
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось подтвердить подготовку.",
      );
    } finally {
      setProtectionBusy(false);
    }
  }

  /** Закрывает preview без отправки: наружу ничего не уходит. */
  function cancelProtection() {
    setProtectionPreview(null);
    setPendingSend(null);
  }

  /** Меняет режим защиты диалога (ADR-0007). */
  async function changeProtectionMode(mode: string) {
    setProtectionMode(mode);
    if (!currentId) return; // применится при создании диалога
    try {
      await api.setProtectionMode(currentId, mode);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось сменить режим.",
      );
      void refreshCurrent();
    }
  }

  /**
   * Собственно отправка и подписка на SSE-поток.
   *
   * @param conversationId Диалог.
   * @param text Текст сообщения.
   * @param options Параметры запроса.
   * @param preparationId Подтверждённая подготовка (только для гибрида).
   */
  async function deliver(
    conversationId: string,
    text: string,
    options: { reasoningDepth?: ReasoningDepth },
    preparationId?: string,
  ) {
    // Оптимистично показываем вопрос пользователя до ответа сервера.
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}`,
        conversation_id: conversationId,
        role: "user",
        content: text,
        parent_id: null,
        status: "completed",
        model_snapshot: {},
        error_code: null,
      },
    ]);

    try {
      const { generation_id } = await api.sendMessage(
        conversationId,
        text,
        selectedModel || undefined,
        options.reasoningDepth,
        // Веб-поиск — разовая операция на сообщение, а не режим сессии:
        // результаты поиска попадают во вход запроса и увеличивают его цену.
        webSearchAvailable && webSearchEnabled,
        preparationId,
      );
      setStreamingId(generation_id);
      setStreaming(true);
      setStreamContent("");

      const es = new EventSource(eventSourceUrl(generation_id));
      esRef.current = es;

      es.addEventListener("content.delta", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        setStreamContent((c) => c + (data.delta ?? ""));
      });
      es.addEventListener("generation.failed", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        setError(data.message ?? "Ошибка генерации.");
        es.close();
        setStreaming(false);
        void refreshCurrent();
      });
      es.addEventListener("generation.completed", () => {
        es.close();
        setStreaming(false);
        void refreshCurrent();
      });
      es.addEventListener("generation.cancelled", () => {
        es.close();
        setStreaming(false);
        void refreshCurrent();
      });
      es.onerror = () => {
        es.close();
        setStreaming(false);
        void refreshCurrent();
      };
    } catch (err) {
      setStreaming(false);
      setError(
        err instanceof Error ? err.message : "Не удалось отправить сообщение.",
      );
      // Оптимистичное сообщение убираем: сервер его не принял.
      void refreshCurrent();
    }
  }

  /** Повторяет последний вопрос пользователя (без создания ветки). */
  function regenerate() {
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) void send(lastUser.content);
  }

  /** Обогащает сообщения API данными расходов и приводит к виду для UI. */
  const viewMessages: ChatMessageView[] = useMemo(
    () =>
      messages.map((m) => {
        const usage = usageByMessage[m.id];
        const snapshotUsage = (m.model_snapshot?.usage ?? {}) as Record<
          string,
          unknown
        >;
        const details = (snapshotUsage.completion_tokens_details ??
          {}) as Record<string, unknown>;
        const reasoning =
          usage?.units_json?.reasoning_tokens ??
          (typeof details.reasoning_tokens === "number"
            ? details.reasoning_tokens
            : undefined);
        // Источники веб-поиска сохранены backend'ом в снимке сообщения: так
        // они переживают перезагрузку страницы и остаются привязаны к ответу.
        const search = (m.model_snapshot?.web_search ?? {}) as {
          used?: boolean;
          warning?: string | null;
          citations?: WebSource[];
        };
        // Режим обработки сохранён backend'ом в снимке защиты сообщения.
        const protection = (m.protection ?? {}) as {
          mode?: string;
          restored?: boolean;
        };
        const privacyMode: ChatMessageView["privacyMode"] =
          protection.mode === "protected_hybrid"
            ? "hybrid"
            : protection.mode === "local_only"
              ? "local"
              : "cloud";
        return {
          id: m.id,
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
          status: m.status,
          errorCode: m.error_code,
          cost: usage?.cost_amount,
          costStatus: usage?.cost_state as ChatMessageView["costStatus"],
          currency: usage?.currency ?? summary?.currency ?? "$",
          tokensIn: usage?.units_json?.input_tokens,
          tokensOut: usage?.units_json?.output_tokens,
          reasoningTokens: reasoning,
          sources: search.used ? (search.citations ?? []) : undefined,
          searchWarning: search.warning ?? null,
          privacyMode,
          restoredLocally: Boolean(protection.restored),
        };
      }),
    [messages, usageByMessage, summary],
  );

  const chatModels: ChatInputModel[] = useMemo(
    () =>
      models.map((m) => ({
        id: m.id,
        name: m.display_name || m.external_model_id,
        // Признак приходит с backend (`has_price`): он вычисляется по наличию
        // PriceSnapshot, поэтому предупреждение появляется ровно там, где
        // платный вызов действительно не будет учтён в бюджете.
        hasPrice: m.has_price,
        // Селектор глубины показываем только для моделей, объявивших
        // capability `reasoning`: провайдер сообщает это в /models, и backend
        // отклонит параметр для модели без поддержки.
        supportsReasoning: m.capabilities.includes("reasoning"),
      })),
    [models],
  );

  const filteredConversations = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return conversations;
    return conversations.filter((c) => c.title.toLowerCase().includes(query));
  }, [conversations, filter]);

  const priceMissing = Boolean(error && error.toLowerCase().includes("цена"));

  return (
    <div className="bg-muted flex h-dvh flex-col">
      <header className="bg-background/70 supports-[backdrop-filter]:bg-background/55 border-border/60 flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2 shadow-[0_1px_0_rgba(15,23,42,0.04)] backdrop-blur-xl">
        <Button
          variant="ghost"
          size="icon-sm"
          className="lg:hidden"
          onClick={() => setSidebarOpen((v) => !v)}
          aria-label="Показать список диалогов"
          aria-expanded={sidebarOpen}
        >
          <Menu />
        </Button>
        <PageHeading level={1} className="text-pah-lg">
          Чат
        </PageHeading>
        <NavigationLinks className="hidden min-w-0 flex-1 md:block" />
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setToken(null);
              router.push("/login");
            }}
          >
            Выйти
          </Button>
        </div>
      </header>

      {/* Панели — «плавающие» карточки с закруглением и мягкой тенью:
          визуально отделяют диалоги и переписку от фона, как в DeepSeek
          Harness. На мобильных отступы и радиус меньше, на десктопе больше. */}
      <div className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[260px_1fr] lg:gap-4 lg:p-5">
        <aside
          className={cn(
            "bg-card min-h-0 flex-col gap-2 overflow-y-auto rounded-2xl border p-3 shadow-[0_12px_32px_-12px_rgba(15,23,42,0.45)] lg:flex dark:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.8)]",
            sidebarOpen ? "flex" : "hidden",
          )}
          aria-label="Диалоги"
        >
          <Button onClick={newConversation} className="w-full">
            <Plus />
            Новый диалог
          </Button>

          <div className="relative">
            <Search
              className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2"
              aria-hidden="true"
            />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Поиск по диалогам"
              aria-label="Поиск по диалогам"
              className="pl-7"
            />
          </div>

          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : filteredConversations.length === 0 ? (
            <p className="text-muted-foreground px-1 text-pah-sm">
              {filter
                ? "Ничего не найдено."
                : "Диалогов пока нет — создайте первый."}
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {filteredConversations.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => openConversation(c.id)}
                    aria-current={c.id === currentId ? "true" : undefined}
                    className={cn(
                      "w-full truncate rounded-md px-2 py-1.5 text-left text-pah-sm transition-colors",
                      c.id === currentId
                        ? "bg-secondary text-secondary-foreground font-medium"
                        : "hover:bg-accent hover:text-accent-foreground",
                    )}
                  >
                    {c.title || "Без названия"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section
          role="main"
          className="bg-card flex min-h-0 flex-col overflow-hidden rounded-2xl border shadow-[0_12px_32px_-12px_rgba(15,23,42,0.45)] dark:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.8)]"
          aria-label="Область переписки"
        >
          {error && (
            <div className="px-4 pt-4">
              <Alert variant="destructive">
                <AlertDescription>
                  {error}{" "}
                  {priceMissing && (
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                      onClick={() => router.push("/models")}
                    >
                      Задать цену модели
                    </Button>
                  )}
                </AlertDescription>
              </Alert>
            </div>
          )}

          {loading ? (
            <div className="mx-auto w-full max-w-3xl space-y-4 p-6">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-4 w-1/4" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : (
            /* MessageList рендерится всегда: область role="log" обязана
               существовать в DOM до появления первого ответа, иначе
               скринридер не объявит его. Пустой диалог показывается внутри
               журнала как EmptyPlaceholder. */
            <MessageList
              messages={viewMessages}
              streamingContent={streamContent}
              isStreaming={streaming}
              onRegenerate={regenerate}
              emptyPlaceholder={
                <EmptyChatState
                  examples={EXAMPLE_PROMPTS}
                  onUseExample={(text) => setDraft(text)}
                  onNewChat={newConversation}
                />
              }
            />
          )}

          {/* Предупреждение показывается НАД полем ввода, а не вместо него:
              иначе при отсутствии моделей у пользователя пропадает композер и
              непонятно, куда возвращаться после настройки провайдера.
              Поле ввода при этом заблокировано. */}
          {models.length === 0 && (
            <div className="px-4 pt-2">
              <Alert>
                <AlertDescription className="flex flex-wrap items-center gap-2">
                  Нет доступных моделей. Добавьте провайдера и синхронизируйте
                  каталог.
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto p-0"
                    onClick={() => router.push("/providers")}
                  >
                    Перейти к провайдерам
                  </Button>
                </AlertDescription>
              </Alert>
            </div>
          )}

          <ChatInput
            models={chatModels}
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
            onSend={(text, options) => void send(text, options)}
            onStop={stopStreaming}
            isStreaming={streaming}
            value={draft}
            onValueChange={setDraft}
            // Тумблер остаётся на месте во всех режимах: в локальном он
            // блокируется, чтобы строка не меняла ширину при переключении.
            webSearchAvailable={webSearchAvailable}
            webSearch={webSearchEnabled}
            onWebSearchChange={setWebSearchEnabled}
            webSearchBlocked={protectionMode === "local_only"}
            protectionAvailable={protectionAvailable}
            protectionMode={protectionMode}
            onProtectionModeChange={(mode) => void changeProtectionMode(mode)}
            protectionBusy={protectionBusy}
            remainingBudget={
              summary
                ? {
                    daily: summary.daily_remaining,
                    currency: summary.currency,
                  }
                : undefined
            }
            onSetupPrice={() => router.push("/models")}
          />
        </section>
      </div>

      {/* Preview подготовки: пользователь видит, что именно уйдёт модели,
          и подтверждает конкретный digest. Наружу до подтверждения ничего
          не отправляется. */}
      <Dialog
        open={protectionPreview !== null}
        onOpenChange={(open) => {
          if (!open) cancelProtection();
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Проверка перед отправкой</DialogTitle>
            <DialogDescription>
              {protectionPreview?.note ??
                "Сверьте очищенный текст: детектор мог пропустить данные."}
            </DialogDescription>
          </DialogHeader>

          {protectionPreview && (
            <div className="flex flex-col gap-3">
              {protectionPreview.entities.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {protectionPreview.entities.map((entity) => (
                    <Badge key={entity.placeholder} variant="secondary">
                      {entity.placeholder} · {entity.category} ×
                      {entity.occurrences}
                    </Badge>
                  ))}
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <span className="text-pah-sm font-medium">Ваш текст</span>
                  <pre className="bg-muted max-h-72 overflow-auto rounded-md p-2 text-pah-xs whitespace-pre-wrap">
                    {protectionPreview.private_messages.join("\n\n")}
                  </pre>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-pah-sm font-medium">
                    Что уйдёт модели
                  </span>
                  <pre className="bg-muted max-h-72 overflow-auto rounded-md p-2 text-pah-xs whitespace-pre-wrap">
                    {protectionPreview.sanitized_text}
                  </pre>
                </div>
              </div>

              <Alert>
                <AlertDescription>
                  Исходные значения останутся на сервере приложения и будут
                  восстановлены в ответе. Проверьте очищенный текст: локальный
                  детектор может пропустить данные, а полной анонимности не
                  гарантирует.
                </AlertDescription>
              </Alert>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={cancelProtection}
              disabled={protectionBusy}
            >
              Отмена
            </Button>
            <Button
              onClick={() => void confirmProtection()}
              disabled={protectionBusy}
            >
              {protectionBusy ? "Отправка…" : "Подтвердить и отправить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
