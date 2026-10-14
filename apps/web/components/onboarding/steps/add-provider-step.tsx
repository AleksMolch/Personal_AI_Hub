"use client";

// Шаг 1 онбординга: добавление провайдера.
//
// Назначение: выбрать пресет (OpenRouter, RouterAI, Selectel, LiteLLM,
// произвольный OpenAI-совместимый), ввести base URL, название и API-ключ,
// затем проверить соединение.
//
// Место в архитектуре: шаг мастера; использует те же эндпоинты, что страница
// «Провайдеры» (`api.presets`, `api.createProvider`, `api.testProvider`).
//
// Безопасность: ключ передаётся один раз в POST /providers, после успешного
// создания стирается из состояния. Проверка соединения не выполняет платных
// вызовов (backend запрашивает только GET /models).
import { useEffect, useId, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, ApiError, Preset } from "@/lib/api";

interface AddProviderStepProps {
  /** Идентификатор уже созданного провайдера (если шаг пройден ранее). */
  providerId: string | null;
  /** Сообщает мастеру о созданном провайдере. */
  onDone: (providerId: string) => void;
  /** Переход к следующему шагу. */
  onNext: () => void;
}

/**
 * Форма добавления первого провайдера.
 *
 * @param props Созданный провайдер и обработчики шага.
 * @returns Поля пресета, названия, base URL и ключа плюс кнопку проверки.
 */
export function AddProviderStep({
  providerId,
  onDone,
  onNext,
}: AddProviderStepProps) {
  const presetId = useId();
  const nameId = useId();
  const urlId = useId();
  const keyId = useId();

  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetType, setPresetType] = useState("openai_compatible");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<string | null>(null);

  useEffect(() => {
    api
      .presets()
      .then((list) => {
        setPresets(list);
        const first =
          list.find((p) => p.provider_type === "openrouter") ?? list[0];
        if (first) {
          setPresetType(first.provider_type);
          setBaseUrl(first.base_url);
          setDisplayName((prev) => prev || first.label);
        }
      })
      .catch(() => setError("Не удалось загрузить список пресетов."));
  }, []);

  /** Подставляет base URL и название выбранного пресета. */
  function applyPreset(type: string) {
    setPresetType(type);
    const preset = presets.find((p) => p.provider_type === type);
    if (preset) {
      setBaseUrl(preset.base_url);
      setDisplayName(preset.label);
    }
  }

  /** Создаёт провайдера и сразу проверяет соединение. */
  async function createAndTest() {
    setError(null);
    setBusy(true);
    try {
      let id = providerId;
      if (!id) {
        const created = await api.createProvider({
          provider_type: presetType,
          display_name: displayName.trim() || "Мой провайдер",
          base_url: baseUrl.trim(),
          api_key: apiKey,
          currency:
            presets.find((p) => p.provider_type === presetType)?.currency ??
            "USD",
        });
        id = created.id;
        onDone(id);
        // Ключ больше не нужен в памяти клиента: backend хранит его
        // зашифрованным, наружу отдаётся только маска.
        setApiKey("");
      }
      const result = await api.testProvider(id);
      setChecked(
        result.ok
          ? `Соединение успешно. Моделей доступно: ${result.model_count}.`
          : `Проверка не прошла: ${result.message}`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Не удалось добавить провайдера.",
      );
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    !busy &&
    baseUrl.trim().length > 0 &&
    (providerId !== null || apiKey.length > 0);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={presetId}>Пресет</Label>
        <Select
          value={presetType}
          onValueChange={applyPreset}
          disabled={providerId !== null}
        >
          <SelectTrigger id={presetId}>
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

      <div className="space-y-2">
        <Label htmlFor={nameId}>Название</Label>
        <Input
          id={nameId}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Мой провайдер"
          disabled={providerId !== null}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor={urlId}>Base URL</Label>
        <Input
          id={urlId}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
          disabled={providerId !== null}
        />
      </div>

      {providerId === null && (
        <div className="space-y-2">
          <Label htmlFor={keyId}>API-ключ</Label>
          <Input
            id={keyId}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="Ключ провайдера"
          />
          <p className="text-muted-foreground text-pah-sm">
            Ключ шифруется на сервере и никогда не возвращается в интерфейс.
          </p>
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {checked && (
        <Alert
          variant={checked.startsWith("Соединение") ? "success" : "warning"}
        >
          <AlertDescription>{checked}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={createAndTest} disabled={!canSubmit}>
          {busy
            ? "Проверка…"
            : providerId
              ? "Проверить соединение"
              : "Добавить и проверить"}
        </Button>
        {checked?.startsWith("Соединение") && (
          <Button variant="outline" onClick={onNext}>
            Далее
          </Button>
        )}
      </div>
    </div>
  );
}
