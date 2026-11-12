import { test, expect } from "@playwright/test";

/**
 * E2E управления диалогами: переименование, теги, фильтр и удаление.
 *
 * Диалоги создаются через API (без вызовов LLM), чтобы тест не тратил бюджет
 * и проверял только интерфейс сайдбара. Названия уникальны для запуска, а
 * прежние тестовые диалоги удаляются, иначе строгие локаторы ловят дубликаты.
 */
const API = "http://127.0.0.1:8000";

test("диалоги: переименование, теги, фильтр, удаление", async ({
  page,
  request,
}) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();

  const token = await page.evaluate(() =>
    window.localStorage.getItem("pah_token"),
  );
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };

  // Чистим хвосты прошлых запусков, чтобы локаторы были однозначными.
  const existing = await request.get(`${API}/api/v1/conversations`, {
    headers,
  });
  for (const conversation of await existing.json()) {
    if (conversation.title.startsWith("E2E-диалог")) {
      await request.delete(`${API}/api/v1/conversations/${conversation.id}`, {
        headers,
      });
    }
  }

  const suffix = Date.now();
  const firstName = `E2E-диалог первый ${suffix}`;
  const secondName = `E2E-диалог второй ${suffix}`;
  const renamed = `E2E-переименованный ${suffix}`;
  const tag = `тег-${suffix}`;

  const first = await request.post(`${API}/api/v1/conversations`, {
    headers,
    data: { title: firstName },
  });
  expect(first.ok()).toBeTruthy();
  const second = await request.post(`${API}/api/v1/conversations`, {
    headers,
    data: { title: secondName },
  });
  expect(second.ok()).toBeTruthy();

  await page.goto("/chat");
  await expect(page.getByText(firstName)).toBeVisible();

  // Переименование через меню строки.
  await page.getByRole("button", { name: `Действия: ${firstName}` }).click();
  await page.getByRole("menuitem", { name: "Переименовать" }).click();
  const renameInput = page.getByLabel(/Новое название диалога/);
  await renameInput.fill(renamed);
  await renameInput.press("Enter");
  await expect(page.getByText(renamed)).toBeVisible();

  // Тег: добавляем через диалог и проверяем чип в строке.
  await page.getByRole("button", { name: `Действия: ${renamed}` }).click();
  await page.getByRole("menuitem", { name: "Теги…" }).click();
  await page.getByLabel("Новый тег").fill(tag);
  await page.getByRole("button", { name: "Добавить" }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText(tag).first()).toBeVisible();

  // Фильтр по тегу оставляет только размеченный диалог.
  await page.getByRole("button", { name: tag, exact: true }).click();
  await expect(page.getByText(renamed)).toBeVisible();
  await expect(page.getByText(secondName)).toHaveCount(0);
  await page.getByRole("button", { name: "Сбросить" }).click();
  await expect(page.getByText(secondName)).toBeVisible();

  // Удаление второго диалога с подтверждением.
  await page.getByRole("button", { name: `Действия: ${secondName}` }).click();
  await page.getByRole("menuitem", { name: "Удалить" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Удалить диалог?")).toBeVisible();
  await dialog.getByRole("button", { name: "Удалить" }).click();
  await expect(page.getByText(secondName)).toHaveCount(0);

  // Убираем за собой первый диалог, чтобы не копить данные в стеке.
  await request.delete(
    `${API}/api/v1/conversations/${(await first.json()).id}`,
    { headers },
  );
});
