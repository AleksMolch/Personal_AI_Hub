"use client";

import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  Citation,
  getToken,
  KnowledgeBase,
  KnowledgeBaseDetail,
  ModelProfile,
  setToken,
} from "@/lib/api";

/**
 * Базы знаний: создание, загрузка документов и RAG-запрос с цитатами.
 */
export default function KnowledgePage() {
  const router = useRouter();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [current, setCurrent] = useState<KnowledgeBaseDetail | null>(null);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [query, setQuery] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [sufficient, setSufficient] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [k, m] = await Promise.all([api.knowledgeBases(), api.models()]);
      setKbs(k);
      setModels(m);
      if (m.length > 0) setModelId(m[0].id);
    } catch (err) {
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

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createKnowledgeBase(name || "База знаний", modelId);
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать.");
    }
  }

  async function onOpen(id: string) {
    setCitations([]);
    setCurrent(await api.getKnowledgeBase(id));
  }

  async function onUpload(e: ChangeEvent<HTMLInputElement>) {
    if (!current || !e.target.files?.length) return;
    setError(null);
    try {
      await api.uploadDocument(current.id, e.target.files[0]);
      setCurrent(await api.getKnowledgeBase(current.id));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось загрузить документ.",
      );
    }
  }

  async function onQuery(e: FormEvent) {
    e.preventDefault();
    if (!current || !query.trim()) return;
    setError(null);
    try {
      const result = await api.queryKnowledgeBase(current.id, query.trim());
      setCitations(result.citations);
      setSufficient(result.sufficient);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка запроса.");
    }
  }

  return (
    <main>
      <header className="row">
        <h1>Базы знаний</h1>
        <div className="row">
          <Link href="/chat">Чат</Link>
          <Link href="/jobs">Задачи</Link>
        </div>
      </header>

      <form onSubmit={onCreate} className="card">
        <h2>Создать базу знаний</h2>
        <div className="row">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название"
          />
          <select value={modelId} onChange={(e) => setModelId(e.target.value)}>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name}
              </option>
            ))}
          </select>
          <button type="submit">Создать</button>
        </div>
      </form>

      <section className="grid">
        <div>
          <h2>Мои базы</h2>
          {kbs.map((kb) => (
            <button
              key={kb.id}
              className={current?.id === kb.id ? "kb-item active" : "kb-item"}
              onClick={() => onOpen(kb.id)}
            >
              {kb.name}
            </button>
          ))}
        </div>

        {current && (
          <div className="card">
            <h2>{current.name}</h2>
            <label>
              Загрузить документ
              <input
                type="file"
                onChange={onUpload}
                accept=".txt,.md,.pdf,.docx"
              />
            </label>
            <p className="hint">Документы:</p>
            {current.documents.map((d) => (
              <div key={d.id} className="hint">
                {d.title} ·{" "}
                <span className={`badge ${d.status}`}>{d.status}</span>
                {d.error_code ? ` · ${d.error_code}` : ""}
              </div>
            ))}

            <form onSubmit={onQuery} className="row">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Задайте вопрос по документам…"
              />
              <button type="submit">Спросить</button>
            </form>
            {!sufficient && (
              <p className="hint">Недостаточно оснований в документах.</p>
            )}
            {citations.map((c) => (
              <div key={c.chunk_id} className="citation">
                <p>{c.text}</p>
                <span className="hint">
                  {c.document_title}
                  {c.page ? ` · стр. ${c.page}` : ""} · {c.score.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
