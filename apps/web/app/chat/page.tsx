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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  Conversation,
  eventSourceUrl,
  getToken,
  Message,
  ModelProfile,
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
        api.capabilities().catch(() => ({ web_search: false })),
      ]);
      setConversations(c);
      setModels(m);
      setSummary(s);
      setWebSearchAvailable(caps.web_search);
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
  async function send(
    content: string,
    options: { reasoningDepth?: ReasoningDepth } = {},
  ) {
    const text = content.trim();
    if (!text || streaming) return;
    setError(null);

    // Диалог создаётся лениво: пользователь может начать писать сразу.
    let conversationId = currentId;
    if (!conversationId) {
      try {
        const conv = await api.createConversation({ title: "Новый диалог" });
        setConversations((c) => [conv, ...c]);
        setCurrentId(conv.id);
        conversationId = conv.id;
      } catch {
        setError("Не удалось создать диалог.");
        return;
      }
    }

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
    <div className="flex h-dvh flex-col">
      <header className="bg-background/95 supports-[backdrop-filter]:bg-background/60 flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2 backdrop-blur">
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
        <h1 className="text-pah-lg font-semibold">Чат</h1>
        <NavigationLinks className="hidden min-w-0 flex-1 md:block" />
        <div className="ml-auto">
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

      <div className="grid min-h-0 flex-1 lg:grid-cols-[260px_1fr]">
        <aside
          className={cn(
            "min-h-0 flex-col gap-2 overflow-y-auto border-b p-3 lg:flex lg:border-r lg:border-b-0",
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
          className="flex min-h-0 flex-col"
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
          ) : viewMessages.length === 0 && !streaming ? (
            <EmptyChatState
              examples={EXAMPLE_PROMPTS}
              onUseExample={(text) => setDraft(text)}
              onNewChat={newConversation}
            />
          ) : (
            <MessageList
              messages={viewMessages}
              streamingContent={streamContent}
              isStreaming={streaming}
              onRegenerate={regenerate}
            />
          )}

          {models.length === 0 ? (
            <div className="border-t p-4">
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
          ) : (
            <ChatInput
              models={chatModels}
              selectedModel={selectedModel}
              onModelChange={setSelectedModel}
              onSend={(text, options) => void send(text, options)}
              onStop={stopStreaming}
              isStreaming={streaming}
              value={draft}
              onValueChange={setDraft}
              webSearchAvailable={webSearchAvailable}
              webSearch={webSearchEnabled}
              onWebSearchChange={setWebSearchEnabled}
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
          )}
        </section>
      </div>
    </div>
  );
}
