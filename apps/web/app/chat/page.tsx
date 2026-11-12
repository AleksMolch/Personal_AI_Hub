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
import {
  Menu,
  MoreHorizontal,
  Plus,
  Scale,
  Search,
  Settings2,
  X,
} from "lucide-react";

import {
  ChatInput,
  type ChatInputModel,
  type ReasoningDepth,
} from "@/components/chat/chat-input";
import { EmptyChatState } from "@/components/chat/empty-chat-state";
import {
  CloudScanDialog,
  type CloudScanResult,
} from "@/components/chat/cloud-scan-dialog";
import { AppHeader } from "@/components/app-header";
import { MessageList } from "@/components/chat/message-list";
import type { ChatMessageView } from "@/components/chat/message";
import { MarkdownRenderer } from "@/components/chat/markdown-renderer";
import type { WebSource } from "@/components/chat/web-sources";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  Conversation,
  downloadBlob,
  eventSourceUrl,
  getToken,
  Message,
  ModelProfile,
  ProtectionPreview,
  PromptTemplate,
  ComparisonItem,
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

/** Параметры отправки одного сообщения. */
type SendOptions = {
  reasoningDepth?: ReasoningDepth;
  temperature?: number;
  maxTokens?: number;
  images?: string[];
};

/** Размер страницы списка диалогов (пагинация на сервере). */
const PAGE_SIZE = 50;

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
    options: SendOptions;
  } | null>(null);
  const [protectionBusy, setProtectionBusy] = useState(false);

  // ADR-0008: предупреждения облака, архив и управление диалогами.
  const [cloudScanEnabled, setCloudScanEnabled] = useState(false);
  const [cloudScan, setCloudScan] = useState<CloudScanResult | null>(null);
  const [pendingCloudSend, setPendingCloudSend] = useState<{
    conversationId: string;
    text: string;
    options: SendOptions;
  } | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [tagsTarget, setTagsTarget] = useState<Conversation | null>(null);
  const [tagsDraft, setTagsDraft] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  // Открытое меню строки: контролируем явно, чтобы закрыть его ДО открытия
  // диалога. Иначе Radix оставляет меню поверх модального окна.
  const [menuId, setMenuId] = useState<string | null>(null);
  // Системный промпт диалога (уровень диалога, а не сообщения).
  const [systemInstruction, setSystemInstruction] = useState("");
  const [sysPromptOpen, setSysPromptOpen] = useState(false);
  const [sysPromptDraft, setSysPromptDraft] = useState("");
  // Библиотека промптов.
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false);
  const [templateTitle, setTemplateTitle] = useState("");
  const [templateContent, setTemplateContent] = useState("");
  // Сравнение моделей side-by-side.
  const [compareOpen, setCompareOpen] = useState(false);
  const [comparePrompt, setComparePrompt] = useState("");
  const [compareModelA, setCompareModelA] = useState("");
  const [compareModelB, setCompareModelB] = useState("");
  const [compareResults, setCompareResults] = useState<ComparisonItem[]>([]);
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  // Пагинация списка диалогов.
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // Редактирование сообщения пользователя (ветвление).
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  /**
   * Загружает диалоги, модели, сводку расходов и записи usage.
   * Стоимость каждого ответа берётся из usage по `message_id`.
   */
  const loadAll = useCallback(async () => {
    try {
      const [c, m, s, records, caps, prompts] = await Promise.all([
        api.conversations(),
        api.models(),
        api.usageSummary().catch(() => null),
        api.usageRecords().catch(() => [] as UsageRecord[]),
        api
          .capabilities()
          .catch(() => ({ web_search: false, protection: undefined })),
        api.prompts().catch(() => [] as PromptTemplate[]),
      ]);
      setConversations(c);
      setModels(m);
      setSummary(s);
      setPromptTemplates(prompts);
      setWebSearchAvailable(caps.web_search);
      setProtectionAvailable(Boolean(caps.protection?.enabled));
      setCloudScanEnabled(Boolean(caps.protection?.cloud_scan));
      // Стартовый режим задаёт сервер (ADR-0008): владелец выбрал «облако с
      // предупреждениями», поэтому не полагаемся на литерал в коде.
      if (caps.protection?.default_mode) {
        setProtectionMode(caps.protection.default_mode);
      }
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
        setSystemInstruction(detail.system_instruction ?? "");
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

  // Поиск по диалогам идёт на сервере (по названию, тегам и содержимому),
  // поэтому меняем список с дебаунсом. Первый прогон пропускаем: список уже
  // загружен loadAll. Архив переключается явным вызовом reloadConversations.
  const skipSearchRef = useRef(true);
  useEffect(() => {
    if (skipSearchRef.current) {
      skipSearchRef.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      void reloadConversations(showArchived);
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- поиск и архив
  }, [filter]);

  // Горячие клавиши: Escape останавливает генерацию, `/` фокусирует поле ввода
  // (только когда фокус не в другом поле ввода/редакторе).
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target &&
        (target.tagName === "TEXTAREA" ||
          target.tagName === "INPUT" ||
          target.isContentEditable);
      if (event.key === "Escape" && streaming) {
        stopStreaming();
        return;
      }
      if (event.key === "/" && !isTyping) {
        event.preventDefault();
        document.querySelector<HTMLTextAreaElement>("textarea")?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- горячие клавиши
  }, [streaming]);

  /** Открывает диалог и загружает его сообщения. */
  async function openConversation(id: string) {
    setCurrentId(id);
    setSidebarOpen(false);
    setError(null);
    try {
      const detail = await api.getConversation(id);
      setMessages(detail.messages);
      setProtectionMode(detail.protection_mode);
      setSystemInstruction(detail.system_instruction ?? "");
    } catch {
      setError("Не удалось открыть диалог.");
    }
  }

  /** Создаёт новый пустой диалог. */
  async function newConversation() {
    try {
      const conv = await api.createConversation({ title: "Новый диалог" });
      // Выбранный режим применяем и к явно созданному диалогу: иначе первый
      // чувствительный текст ушёл бы в облако, хотя в селекторе стоит гибрид.
      if (protectionAvailable && protectionMode !== "cloud_controlled") {
        await api.setProtectionMode(conv.id, protectionMode);
      }
      setCurrentId(conv.id);
      setMessages([]);
      setSidebarOpen(false);
      setError(null);
      // В режиме просмотра архива новый диалог в список не попадёт: выходим из
      // архива, чтобы пользователь увидел созданную строку.
      if (showArchived) {
        await reloadConversations(false);
      } else {
        setConversations((c) => [conv, ...c]);
      }
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
  async function send(content: string, options: SendOptions = {}) {
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
        // Модель передаём обязательно: окно контекста в prepare должно совпасть
        // с отправкой, иначе digest не сойдётся при малом контексте модели.
        const preview = await api.prepareProtection(
          conversationId,
          text,
          selectedModel || undefined,
        );
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

    // ADR-0008: в облачном режиме локально проверяем текст и показываем
    // категории. Это предупреждение, а не блокировка: сбой сканирования не
    // должен останавливать работу.
    if (
      protectionMode === "cloud_controlled" &&
      cloudScanEnabled &&
      !streaming
    ) {
      try {
        const result = await api.scanProtection(text);
        if (result.categories.length > 0 || result.has_secret) {
          setCloudScan(result);
          setPendingCloudSend({ conversationId, text, options });
          return;
        }
      } catch {
        // Локальная проверка — подсказка. Если она недоступна, отправляем как
        // раньше: молча блокировать чат из-за сбоя детектора нельзя.
      }
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

  /** Подтверждает отправку в облако после предупреждения (ADR-0008). */
  function sendCloudAnyway() {
    if (!pendingCloudSend) return;
    const pending = pendingCloudSend;
    setCloudScan(null);
    setPendingCloudSend(null);
    void deliver(
      pending.conversationId,
      pending.text,
      pending.options,
      undefined,
      true,
    );
  }

  /** Отмена предупреждения: ничего не отправляется. */
  function cancelCloudScan() {
    setCloudScan(null);
    setPendingCloudSend(null);
  }

  /** Из предупреждения облака переходит в гибрид и готовит preview. */
  async function switchCloudToHybrid() {
    if (!pendingCloudSend) return;
    const pending = pendingCloudSend;
    setCloudScan(null);
    setPendingCloudSend(null);
    await changeProtectionMode("protected_hybrid");
    setProtectionBusy(true);
    try {
      const preview = await api.prepareProtection(
        pending.conversationId,
        pending.text,
        selectedModel || undefined,
      );
      setProtectionPreview(preview);
      setPendingSend(pending);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось подготовить защищённый запрос.",
      );
    } finally {
      setProtectionBusy(false);
    }
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
    options: SendOptions,
    preparationId?: string,
    cloudScanAcknowledged = false,
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
        cloudScanAcknowledged,
        options.temperature,
        options.maxTokens,
        options.images,
      );
      subscribeGeneration(generation_id);
    } catch (err) {
      setStreaming(false);
      setError(
        err instanceof Error ? err.message : "Не удалось отправить сообщение.",
      );
      // Оптимистичное сообщение убираем: сервер его не принял.
      void refreshCurrent();
    }
  }

  /** Подписывается на SSE-поток генерации и ведёт состояние диалога. */
  function subscribeGeneration(generationId: string) {
    setStreamingId(generationId);
    setStreaming(true);
    setStreamContent("");

    const es = new EventSource(eventSourceUrl(generationId));
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
  }

  /** Перегенерирует ответ ассистента для его вопроса (ветвление). */
  async function regenerate(assistantMessageId: string) {
    if (streaming) return;
    const assistant = messages.find((m) => m.id === assistantMessageId);
    if (!assistant?.parent_id || !currentId) return;
    setError(null);
    try {
      const { generation_id } = await api.regenerateMessage(
        currentId,
        assistant.parent_id,
      );
      subscribeGeneration(generation_id);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось перегенерировать ответ.",
      );
      void refreshCurrent();
    }
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
              : protection.mode === "direct_cloud"
                ? "direct"
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

  /** Уникальные теги всех загруженных диалогов для панели фильтров. */
  const allTags = useMemo(() => {
    const byKey = new Map<string, string>();
    for (const conversation of conversations) {
      for (const tag of conversation.tags) {
        const key = tag.toLowerCase();
        if (!byKey.has(key)) byKey.set(key, tag);
      }
    }
    return [...byKey.values()].sort((a, b) => a.localeCompare(b, "ru"));
  }, [conversations]);

  const filteredConversations = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return conversations.filter((c) => {
      // Поиск идёт и по названию, и по тегам: пользователь часто помнит
      // метку, а не заголовок.
      const matchesQuery =
        !query ||
        c.title.toLowerCase().includes(query) ||
        c.tags.some((tag) => tag.toLowerCase().includes(query));
      // Несколько выбранных тегов означают «И»: так проще сузить выборку.
      const matchesTags = selectedTags.every((wanted) =>
        c.tags.some((tag) => tag.toLowerCase() === wanted.toLowerCase()),
      );
      return matchesQuery && matchesTags;
    });
  }, [conversations, filter, selectedTags]);

  /** Сколько старых сообщений не ушло провайдеру в последнем ответе. */
  const droppedContext = useMemo(() => {
    const lastAssistant = [...messages]
      .reverse()
      .find((message) => message.role === "assistant");
    const context = (
      lastAssistant?.model_snapshot as
        { context?: { dropped?: number } } | undefined
    )?.context;
    return context?.dropped ?? 0;
  }, [messages]);

  /** Загружает первую страницу диалогов (сброс списка и флага «ещё»). */
  async function reloadConversations(archived: boolean, q = filter) {
    try {
      const list = await api.conversations(archived, q, PAGE_SIZE, 0);
      setConversations(list);
      setShowArchived(archived);
      setHasMore(list.length === PAGE_SIZE);
    } catch {
      setError("Не удалось загрузить диалоги.");
    }
  }

  /** Догружает следующую страницу диалогов (без сброса текущего списка). */
  async function loadMoreConversations() {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const more = await api.conversations(
        showArchived,
        filter,
        PAGE_SIZE,
        conversations.length,
      );
      setConversations((c) => [...c, ...more]);
      setHasMore(more.length === PAGE_SIZE);
    } catch {
      setError("Не удалось загрузить диалоги.");
    } finally {
      setLoadingMore(false);
    }
  }

  /** Начинает переименование диалога. */
  function startRename(conversation: Conversation) {
    setRenameId(conversation.id);
    setRenameValue(conversation.title);
  }

  /** Сохраняет новое название и обновляет строку без перезагрузки. */
  async function commitRename() {
    const id = renameId;
    const title = renameValue.trim();
    setRenameId(null);
    if (!id || !title) return;
    try {
      const updated = await api.updateConversation(id, { title });
      setConversations((list) =>
        list.map((c) => (c.id === updated.id ? updated : c)),
      );
    } catch {
      setError("Не удалось переименовать диалог.");
    }
  }

  /** Открывает редактор тегов для диалога. */
  function openTags(conversation: Conversation) {
    setTagsTarget(conversation);
    setTagsDraft(conversation.tags);
    setTagInput("");
  }

  /** Добавляет тег из поля ввода (без дублей по регистру). */
  function addTag() {
    const tag = tagInput.trim();
    if (!tag) return;
    if (!tagsDraft.some((item) => item.toLowerCase() === tag.toLowerCase())) {
      setTagsDraft((tags) => [...tags, tag]);
    }
    setTagInput("");
  }

  /** Сохраняет теги диалога. */
  async function saveTags() {
    const target = tagsTarget;
    if (!target) return;
    setTagsTarget(null);
    try {
      const updated = await api.updateConversation(target.id, {
        tags: tagsDraft,
      });
      setConversations((list) =>
        list.map((c) => (c.id === updated.id ? updated : c)),
      );
    } catch {
      setError("Не удалось сохранить теги.");
    }
  }

  /** Архивирует или возвращает диалог из архива. */
  async function toggleArchive(conversation: Conversation) {
    try {
      await api.updateConversation(conversation.id, {
        archived: !conversation.archived,
      });
      await reloadConversations(showArchived);
    } catch {
      setError("Не удалось изменить архив диалога.");
    }
  }

  /** Скачивает диалог в markdown. */
  async function exportConversation(conversation: Conversation) {
    try {
      const blob = await api.exportConversation(conversation.id);
      const safeName =
        conversation.title.replace(/[\\/:*?"<>|]+/g, "-").trim() || "dialog";
      downloadBlob(blob, `${safeName}.md`);
    } catch {
      setError("Не удалось экспортировать диалог.");
    }
  }

  /** Удаляет диалог после подтверждения и очищает состояние. */
  async function confirmDelete() {
    const target = deleteTarget;
    if (!target) return;
    setDeleteTarget(null);
    try {
      await api.deleteConversation(target.id);
      const nextList = conversations.filter((c) => c.id !== target.id);
      setConversations(nextList);
      if (currentId === target.id) {
        esRef.current?.close();
        setStreamingId(null);
        setStreaming(false);
        setStreamContent("");
        setMessages([]);
        setProtectionPreview(null);
        setPendingSend(null);
        setCurrentId(null);
        const next = nextList[0];
        if (next) await openConversation(next.id);
      }
    } catch {
      setError("Не удалось удалить диалог.");
    }
  }

  /** Открывает редактор системного промпта диалога. */
  function openSystemPrompt() {
    setSysPromptDraft(systemInstruction);
    setSysPromptOpen(true);
  }

  /** Сохраняет системный промпт диалога (пустое значение снимает инструкцию). */
  async function saveSystemPrompt() {
    if (!currentId) return;
    const value = sysPromptDraft.trim();
    try {
      const updated = await api.updateConversation(currentId, {
        system_instruction: value || null,
      });
      setConversations((list) =>
        list.map((c) => (c.id === updated.id ? updated : c)),
      );
      setSystemInstruction(value);
      setSysPromptOpen(false);
    } catch {
      setError("Не удалось сохранить инструкцию.");
    }
  }

  /** Открывает редактор сообщения пользователя. */
  function startEdit(messageId: string) {
    const target = messages.find((m) => m.id === messageId);
    if (!target) return;
    setEditingMessageId(messageId);
    setEditDraft(target.content);
  }

  /** Сохраняет правку и перегенерирует ответ от этого сообщения. */
  async function saveEdit() {
    if (!currentId || !editingMessageId) return;
    const content = editDraft.trim();
    const messageId = editingMessageId;
    if (!content) {
      setEditingMessageId(null);
      return;
    }
    setEditingMessageId(null);
    try {
      await api.editMessage(currentId, messageId, content);
      // Показать обрезанный диалог, затем перегенерировать ответ.
      await refreshCurrent();
      const { generation_id } = await api.regenerateMessage(
        currentId,
        messageId,
      );
      subscribeGeneration(generation_id);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось отредактировать сообщение.",
      );
      void refreshCurrent();
    }
  }

  /** Вставляет шаблон в поле ввода. */
  function useTemplate(content: string) {
    setDraft(content);
  }

  /** Открывает диалог сохранения текущего текста как шаблона. */
  function openSaveTemplate(content: string) {
    setTemplateContent(content);
    setTemplateTitle("");
    setSaveTemplateOpen(true);
  }

  /** Сохраняет шаблон и обновляет список. */
  async function confirmSaveTemplate() {
    const title = templateTitle.trim();
    if (!title || !templateContent) return;
    try {
      const created = await api.createPrompt({
        title,
        content: templateContent,
      });
      setPromptTemplates((t) => [created, ...t]);
      setSaveTemplateOpen(false);
    } catch {
      setError("Не удалось сохранить шаблон.");
    }
  }

  /** Удаляет шаблон. */
  async function deleteTemplate(id: string) {
    try {
      await api.deletePrompt(id);
      setPromptTemplates((t) => t.filter((x) => x.id !== id));
    } catch {
      setError("Не удалось удалить шаблон.");
    }
  }

  /** Запускает сравнение двух моделей на одном промпте. */
  async function runComparison() {
    const prompt = comparePrompt.trim();
    if (!prompt || !compareModelA || !compareModelB || compareBusy) return;
    setCompareBusy(true);
    setCompareError(null);
    setCompareResults([]);
    try {
      const result = await api.compareModels({
        prompt,
        model_profile_ids: [compareModelA, compareModelB],
      });
      setCompareResults(result.results);
    } catch (err) {
      setCompareError(
        err instanceof Error ? err.message : "Не удалось выполнить сравнение.",
      );
    } finally {
      setCompareBusy(false);
    }
  }

  const priceMissing = Boolean(error && error.toLowerCase().includes("цена"));

  // Ширина сайдбара: живёт в состоянии и не сохраняется, чтобы при смене окна
  // панель не «залипала» в неудобном размере.
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const resizeRef = useRef<{
    startX: number;
    startValue: number;
    max: number;
  } | null>(null);

  const SIDEBAR_MIN = 200;
  const SIDEBAR_MAX = 420;

  /** Ограничивает значение диапазоном. */
  function clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
  }

  /** Начинает перетаскивание правой грани сайдбара. */
  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    resizeRef.current = {
      startX: event.clientX,
      startValue: sidebarWidth,
      max: SIDEBAR_MAX,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    // Пока тянем — не выделяем текст и держим курсор нужной формы.
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  }

  /** Обновляет ширину во время перетаскивания. */
  function moveResize(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = resizeRef.current;
    if (!drag) return;
    setSidebarWidth(
      clamp(
        drag.startValue + (event.clientX - drag.startX),
        SIDEBAR_MIN,
        drag.max,
      ),
    );
  }

  /** Завершает перетаскивание и убирает временные стили. */
  function endResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!resizeRef.current) return;
    resizeRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  }

  /** Двойной клик по ручке возвращает ширину по умолчанию. */
  function resetResize() {
    setSidebarWidth(260);
  }

  /** Клавиатурная регулировка: стрелки двигают грань на 16 px. */
  function nudgeResize(delta: number) {
    setSidebarWidth((w) => clamp(w + delta, SIDEBAR_MIN, SIDEBAR_MAX));
  }

  return (
    <div className="bg-muted flex h-dvh flex-col">
      <AppHeader
        leading={
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
        }
      />

      {/* Панели — «плавающие» карточки с закруглением и мягкой тенью:
          визуально отделяют диалоги и переписку от фона, как в DeepSeek
          Harness. На мобильных отступы и радиус меньше, на десктопе больше.
          Ширина сайдбара задаётся переменной и тянется за правую грань;
          высота области чата при перетаскивании верхней грани — inline-стилем,
          при этом низ панели остаётся прижат к низу окна. */}
      <div
        ref={gridRef}
        className="grid min-h-0 flex-1 gap-3 p-3 lg:grid-cols-[var(--sidebar-width,260px)_1fr] lg:gap-4 lg:p-5"
        style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
      >
        <aside
          className={cn(
            "bg-card relative min-h-0 rounded-2xl border shadow-[0_12px_32px_-12px_rgba(15,23,42,0.45)] dark:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.8)]",
            sidebarOpen ? "block" : "hidden",
            "lg:block",
          )}
          aria-label="Диалоги"
        >
          <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto p-3">
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
                placeholder="Поиск по названию и тегам"
                aria-label="Поиск по диалогам"
                className="pl-7"
              />
            </div>

            {allTags.length > 0 && (
              <div
                className="flex flex-wrap items-center gap-1"
                aria-label="Фильтр по тегам"
              >
                {allTags.map((tag) => {
                  const active = selectedTags.some(
                    (item) => item.toLowerCase() === tag.toLowerCase(),
                  );
                  return (
                    <button
                      key={tag}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setSelectedTags((tags) =>
                          active
                            ? tags.filter(
                                (item) =>
                                  item.toLowerCase() !== tag.toLowerCase(),
                              )
                            : [...tags, tag],
                        )
                      }
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-pah-xs transition-colors",
                        active
                          ? "bg-secondary text-secondary-foreground border-transparent"
                          : "text-muted-foreground hover:bg-accent",
                      )}
                    >
                      {tag}
                    </button>
                  );
                })}
                {selectedTags.length > 0 && (
                  <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground text-pah-xs underline"
                    onClick={() => setSelectedTags([])}
                  >
                    Сбросить
                  </button>
                )}
              </div>
            )}

            <div className="flex items-center justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground h-7 px-2 text-pah-xs"
                onClick={() => void reloadConversations(!showArchived)}
              >
                {showArchived ? "Скрыть архив" : "Показать архив"}
              </Button>
              <span className="text-muted-foreground text-pah-xs">
                {filteredConversations.length} из {conversations.length}
              </span>
            </div>

            {hasMore && !loading && (
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground h-7 w-full text-pah-xs"
                onClick={() => void loadMoreConversations()}
                disabled={loadingMore}
              >
                {loadingMore ? "Загрузка…" : "Показать ещё"}
              </Button>
            )}

            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </div>
            ) : filteredConversations.length === 0 ? (
              <p className="text-muted-foreground px-1 text-pah-sm">
                {filter || selectedTags.length
                  ? "Ничего не найдено."
                  : showArchived
                    ? "Архив пуст."
                    : "Диалогов пока нет — создайте первый."}
              </p>
            ) : (
              <ul className="flex flex-col gap-1">
                {filteredConversations.map((c) => (
                  <li key={c.id}>
                    <div
                      className={cn(
                        "rounded-md transition-colors",
                        c.id === currentId
                          ? "bg-secondary"
                          : "hover:bg-accent/60",
                      )}
                    >
                      <div className="flex items-center gap-1">
                        {renameId === c.id ? (
                          <form
                            className="flex min-w-0 flex-1 items-center gap-1 px-1 py-0.5"
                            onSubmit={(event) => {
                              event.preventDefault();
                              void commitRename();
                            }}
                          >
                            <Input
                              autoFocus
                              value={renameValue}
                              onChange={(e) => setRenameValue(e.target.value)}
                              onKeyDown={(event) => {
                                if (event.key === "Escape") {
                                  event.preventDefault();
                                  setRenameId(null);
                                }
                              }}
                              aria-label={`Новое название диалога ${c.title}`}
                              className="h-7 text-pah-sm"
                            />
                            <Button
                              type="submit"
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-pah-xs"
                            >
                              ОК
                            </Button>
                          </form>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void openConversation(c.id)}
                            onDoubleClick={() => startRename(c)}
                            aria-current={
                              c.id === currentId ? "true" : undefined
                            }
                            className="min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-left text-pah-sm"
                            title={c.title}
                          >
                            {c.title || "Без названия"}
                          </button>
                        )}
                        <DropdownMenu
                          open={menuId === c.id}
                          onOpenChange={(open) => setMenuId(open ? c.id : null)}
                        >
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Действия: ${c.title}`}
                            >
                              <MoreHorizontal />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onSelect={() => startRename(c)}>
                              Переименовать
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() => {
                                setMenuId(null);
                                // Диалог открываем после закрытия меню: иначе
                                // фокус-ловушка модалки оставляет меню поверх.
                                window.setTimeout(() => openTags(c), 0);
                              }}
                            >
                              Теги…
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() => void toggleArchive(c)}
                            >
                              {c.archived ? "Вернуть из архива" : "В архив"}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() => void exportConversation(c)}
                            >
                              Экспорт .md
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onSelect={() => {
                                setMenuId(null);
                                window.setTimeout(() => setDeleteTarget(c), 0);
                              }}
                              className="text-destructive"
                            >
                              Удалить
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      {c.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 px-2 pb-1.5">
                          {c.tags.map((tag) => (
                            <span
                              key={tag}
                              className="bg-muted text-muted-foreground rounded px-1 text-pah-xs"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Ручка ширины: тонкая полоса в зазоре между панелями. На
              мобильных скрыта — там сайдбар открывается кнопкой в шапке. */}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Изменить ширину панели диалогов"
            aria-valuenow={sidebarWidth}
            aria-valuemin={SIDEBAR_MIN}
            aria-valuemax={SIDEBAR_MAX}
            aria-valuetext={`${sidebarWidth} пикселей`}
            tabIndex={0}
            title="Потяните, чтобы изменить ширину. Двойной клик — сбросить"
            className="group absolute inset-y-0 -right-2 z-10 hidden w-4 cursor-col-resize touch-none items-center justify-center lg:flex"
            onPointerDown={startResize}
            onPointerMove={moveResize}
            onPointerUp={endResize}
            onPointerCancel={endResize}
            onDoubleClick={resetResize}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                nudgeResize(-16);
              }
              if (event.key === "ArrowRight") {
                event.preventDefault();
                nudgeResize(16);
              }
            }}
          >
            <span className="bg-border group-hover:bg-primary/60 h-10 w-1 rounded-full transition-colors" />
          </div>
        </aside>

        <section
          role="main"
          className="bg-card flex min-h-0 flex-col overflow-hidden rounded-2xl border shadow-[0_12px_32px_-12px_rgba(15,23,42,0.45)] dark:shadow-[0_12px_32px_-12px_rgba(0,0,0,0.8)]"
          aria-label="Область переписки"
        >
          {/* Заголовок скрыт визуально: в шапке он сдвигал навигацию, и меню
              «прыгало» относительно других разделов. Для скринридеров и
              заголовочной структуры h1 остаётся внутри landmark-области. */}
          <h1 className="sr-only">Чат</h1>
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

          {/* Панель инструментов диалога: компактная строка над перепиской.
              Системный промпт — настройка уровня диалога, поэтому живёт здесь,
              а не в композере (у композера — параметры следующего сообщения). */}
          <div className="flex items-center justify-end gap-1 border-b px-3 py-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCompareOpen(true)}
              aria-label="Сравнить модели"
              title="Сравнить две модели на одном промпте"
            >
              <Scale />
              Сравнить
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={openSystemPrompt}
              aria-label="Настройки диалога"
              title="Системный промпт диалога"
            >
              <Settings2 />
              {systemInstruction ? "Инструкция" : "Настройки"}
            </Button>
          </div>

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
              onEdit={startEdit}
              emptyPlaceholder={
                <EmptyChatState
                  examples={EXAMPLE_PROMPTS}
                  onUseExample={(text) => setDraft(text)}
                  onNewChat={newConversation}
                />
              }
            />
          )}

          {/* Окно контекста: объясняем, почему модель не видит ранние
              сообщения, вместо тихого усечения (ADR-0008). */}
          {droppedContext > 0 && (
            <p className="text-muted-foreground px-4 pt-2 text-pah-xs">
              В последний запрос не вошли {droppedContext} старых сообщений —
              лимит контекста.
            </p>
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
            promptTemplates={promptTemplates}
            onUseTemplate={useTemplate}
            onSaveTemplate={openSaveTemplate}
            onDeleteTemplate={(id) => void deleteTemplate(id)}
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

      <CloudScanDialog
        open={cloudScan !== null}
        scan={cloudScan}
        busy={protectionBusy}
        onCancel={cancelCloudScan}
        onSendAnyway={sendCloudAnyway}
        onUseHybrid={() => void switchCloudToHybrid()}
      />

      {/* Системный промпт диалога: применяется ко всем сообщениям этого диалога.
          Пустое поле снимает инструкцию (system_instruction = null). */}
      <Dialog
        open={sysPromptOpen}
        onOpenChange={(open) => !open && setSysPromptOpen(false)}
      >
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Инструкция диалога</DialogTitle>
            <DialogDescription>
              Задайте роль и правила для модели — они будут действовать на все
              ответы в этом диалоге. Пустое поле отключает инструкцию.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={sysPromptDraft}
            onChange={(e) => setSysPromptDraft(e.target.value)}
            placeholder="Например: отвечай кратко, по-русски, без списков."
            aria-label="Системный промпт диалога"
            className="min-h-28"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSysPromptOpen(false)}>
              Отмена
            </Button>
            <Button onClick={() => void saveSystemPrompt()}>Сохранить</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Редактирование сообщения пользователя: сохранение обрезает старую
          ветку и перегенерирует ответ (ADR-0009, ветвление). */}
      <Dialog
        open={editingMessageId !== null}
        onOpenChange={(open) => !open && setEditingMessageId(null)}
      >
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Редактировать сообщение</DialogTitle>
            <DialogDescription>
              После сохранения ответ и все последующие сообщения этой ветки
              будут перегенерированы.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={editDraft}
            onChange={(e) => setEditDraft(e.target.value)}
            aria-label="Текст сообщения"
            className="min-h-28"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingMessageId(null)}>
              Отмена
            </Button>
            <Button onClick={() => void saveEdit()}>
              Сохранить и перегенерировать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Сохранение текущего текста как шаблона промпта. */}
      <Dialog
        open={saveTemplateOpen}
        onOpenChange={(open) => !open && setSaveTemplateOpen(false)}
      >
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Сохранить шаблон</DialogTitle>
            <DialogDescription>
              Шаблон появится в библиотеке промптов и его можно будет вставить в
              любое поле ввода.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="prompt-template-title" className="text-pah-sm">
              Название
            </Label>
            <Input
              id="prompt-template-title"
              value={templateTitle}
              onChange={(e) => setTemplateTitle(e.target.value)}
              placeholder="Например, Письмо клиенту"
              maxLength={120}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSaveTemplateOpen(false)}
            >
              Отмена
            </Button>
            <Button onClick={() => void confirmSaveTemplate()}>
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Сравнение моделей: один промпт, два ответа. Оба вызова тарифицируются. */}
      <Dialog
        open={compareOpen}
        onOpenChange={(open) => !open && setCompareOpen(false)}
      >
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Сравнить модели</DialogTitle>
            <DialogDescription>
              Один промпт отправится обеим моделям; стоимость каждого ответа
              учтётся в бюджете.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="compare-prompt" className="text-pah-sm">
              Промпт
            </Label>
            <Textarea
              id="compare-prompt"
              value={comparePrompt}
              onChange={(e) => setComparePrompt(e.target.value)}
              placeholder="Сравните ответы двух моделей…"
              className="min-h-20"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="compare-a" className="text-pah-sm">
                Модель A
              </Label>
              <select
                id="compare-a"
                value={compareModelA}
                onChange={(e) => setCompareModelA(e.target.value)}
                className="bg-background border-input w-full rounded-md border px-2 py-1.5 text-pah-sm"
              >
                <option value="">Выберите модель</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name || m.external_model_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="compare-b" className="text-pah-sm">
                Модель B
              </Label>
              <select
                id="compare-b"
                value={compareModelB}
                onChange={(e) => setCompareModelB(e.target.value)}
                className="bg-background border-input w-full rounded-md border px-2 py-1.5 text-pah-sm"
              >
                <option value="">Выберите модель</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name || m.external_model_id}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {compareError && (
            <p className="text-destructive text-pah-sm" role="alert">
              {compareError}
            </p>
          )}

          {compareResults.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {compareResults.map((item) => (
                <div
                  key={item.model_profile_id}
                  className="rounded-md border p-3"
                >
                  <div className="text-pah-sm mb-2 font-medium">
                    {item.display_name}
                  </div>
                  <div className="max-h-72 overflow-y-auto text-pah-sm">
                    <MarkdownRenderer content={item.content} />
                  </div>
                </div>
              ))}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setCompareOpen(false)}>
              Закрыть
            </Button>
            <Button
              onClick={() => void runComparison()}
              disabled={
                compareBusy ||
                !comparePrompt.trim() ||
                !compareModelA ||
                !compareModelB
              }
            >
              {compareBusy ? "Сравнение…" : "Сравнить"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Редактор тегов: до 10 тегов, каждый до 24 символов — те же
          ограничения проверяет сервер. */}
      <Dialog
        open={Boolean(tagsTarget)}
        onOpenChange={(open) => !open && setTagsTarget(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Теги диалога</DialogTitle>
            <DialogDescription>
              До 10 тегов, каждый до 24 символов. Фильтр в списке ищет по
              названию и тегам.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-wrap gap-1">
            {tagsDraft.map((tag) => (
              <Badge key={tag} variant="secondary" className="gap-1">
                {tag}
                <button
                  type="button"
                  aria-label={`Удалить тег ${tag}`}
                  onClick={() =>
                    setTagsDraft((tags) => tags.filter((t) => t !== tag))
                  }
                >
                  <X className="size-3" />
                </button>
              </Badge>
            ))}
            {tagsDraft.length === 0 && (
              <span className="text-muted-foreground text-pah-sm">
                Тегов пока нет.
              </span>
            )}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              addTag();
            }}
          >
            <Input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              placeholder="Например, работа"
              aria-label="Новый тег"
              maxLength={24}
            />
            <Button type="submit" variant="outline">
              Добавить
            </Button>
          </form>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTagsTarget(null)}>
              Отмена
            </Button>
            <Button onClick={() => void saveTags()}>Сохранить</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Удаление необратимо, поэтому подтверждение обязательно. */}
      <Dialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Удалить диалог?</DialogTitle>
            <DialogDescription>
              «{deleteTarget?.title ?? ""}» и все сообщения будут удалены
              безвозвратно. Записи расходов останутся в отчёте.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Отмена
            </Button>
            <Button variant="destructive" onClick={() => void confirmDelete()}>
              Удалить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
