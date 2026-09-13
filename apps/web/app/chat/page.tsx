"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  Conversation,
  eventSourceUrl,
  getToken,
  Message,
  ModelProfile,
  setToken,
} from "@/lib/api";

/**
 * Чат: список диалогов, сообщения и потоковый вывод через SSE.
 */
export default function ChatPage() {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamContent, setStreamContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      const [c, m] = await Promise.all([api.conversations(), api.models()]);
      setConversations(c);
      setModels(m);
      if (m.length > 0) setSelectedModel(m[0].id);
    } catch {
      setError("Не удалось загрузить данные.");
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch на mount
    void loadConversations();
    return () => esRef.current?.close();
  }, [loadConversations, router]);

  async function openConversation(id: string) {
    setCurrentId(id);
    const detail = await api.getConversation(id);
    setMessages(detail.messages);
  }

  async function newConversation() {
    const conv = await api.createConversation({ title: "Новый диалог" });
    setConversations((c) => [conv, ...c]);
    setCurrentId(conv.id);
    setMessages([]);
  }

  function stopStreaming() {
    esRef.current?.close();
    setStreaming(false);
    if (streamingId) {
      api.cancelGeneration(streamingId).catch(() => undefined);
    }
  }

  async function onSend(e: FormEvent) {
    e.preventDefault();
    const content = input.trim();
    if (!content || !currentId || streaming) return;
    setError(null);
    setInput("");

    // Оптимистично добавляем сообщение пользователя.
    setMessages((msgs) => [
      ...msgs,
      {
        id: `user-${Date.now()}`,
        conversation_id: currentId,
        role: "user",
        content,
        parent_id: null,
        status: "completed",
        model_snapshot: {},
        error_code: null,
      },
    ]);

    try {
      const { generation_id } = await api.sendMessage(
        currentId,
        content,
        selectedModel || undefined,
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
        void refreshAfterStream();
      });
      es.addEventListener("generation.completed", () => {
        es.close();
        setStreaming(false);
        void refreshAfterStream();
      });
      es.addEventListener("generation.cancelled", () => {
        es.close();
        setStreaming(false);
        void refreshAfterStream();
      });
      es.onerror = () => {
        es.close();
        setStreaming(false);
        void refreshAfterStream();
      };
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось отправить сообщение.",
      );
    }
  }

  async function refreshAfterStream() {
    if (currentId) {
      try {
        const detail = await api.getConversation(currentId);
        setMessages(detail.messages);
      } catch {
        // ignore
      }
    }
    setStreamContent("");
  }

  function logout() {
    setToken(null);
    router.push("/login");
  }

  return (
    <main className="chat-layout">
      <aside className="sidebar">
        <header className="row">
          <h1>Чат</h1>
        </header>
        <button onClick={newConversation}>+ Новый диалог</button>
        <div className="conv-list">
          {conversations.map((c) => (
            <button
              key={c.id}
              className={c.id === currentId ? "active" : ""}
              onClick={() => openConversation(c.id)}
            >
              {c.title}
            </button>
          ))}
        </div>
        <div className="row sidebar-footer">
          <Link href="/providers">Провайдеры</Link>
          <button className="link" onClick={logout}>
            Выйти
          </button>
        </div>
      </aside>

      <section className="chat-main">
        {currentId ? (
          <>
            <div className="messages">
              {messages.map((m) => (
                <div key={m.id} className={`bubble ${m.role}`}>
                  <div className="role">
                    {m.role === "user" ? "Вы" : "Ассистент"}
                  </div>
                  <p>
                    {m.content ||
                      (m.status === "failed" ? `Ошибка: ${m.error_code}` : "")}
                  </p>
                </div>
              ))}
              {streaming && (
                <div className="bubble assistant">
                  <div className="role">Ассистент</div>
                  <p>{streamContent || "…"}</p>
                </div>
              )}
            </div>

            <form className="composer" onSubmit={onSend}>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                aria-label="Модель"
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name}
                  </option>
                ))}
              </select>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Введите сообщение…"
                disabled={streaming}
              />
              {streaming ? (
                <button type="button" onClick={stopStreaming}>
                  Стоп
                </button>
              ) : (
                <button type="submit">Отправить</button>
              )}
            </form>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </>
        ) : (
          <p className="hint">Выберите или создайте диалог.</p>
        )}
      </section>
    </main>
  );
}
