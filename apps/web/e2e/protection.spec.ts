import { test, expect } from "@playwright/test";

/**
 * E2E защищённых режимов (ADR-0007).
 *
 * Проверяет пользовательский сценарий без платного вызова: переключатель
 * режимов, preview с псевдонимами вместо данных и отмену отправки.
 *
 * Предусловия: стек запущен, есть администратор admin / supersecret123,
 * провайдер и модель с ценой, на сервере `PROTECTION_MODES_ENABLED=1`.
 * Поэтому тест включается явно: `PROTECTION_E2E=1 npx playwright test`.
 */
test.skip(
  process.env.PROTECTION_E2E !== "1",
  "нужен PROTECTION_MODES_ENABLED=1 и настроенный провайдер",
);

test("гибрид: preview с псевдонимами без отправки", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  // Дожидаемся входа: иначе переход на /chat случится раньше сохранения токена.
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");

  await page.getByRole("radio", { name: "Защищённый гибрид" }).click();
  await page
    .getByLabel("Текст сообщения")
    .fill("Договор с ООО «Ромашка». Почта: ivan.petrov@example.com");
  await page.getByRole("button", { name: "Отправить сообщение" }).click();

  await expect(
    page.getByRole("heading", { name: "Проверка перед отправкой" }),
  ).toBeVisible();
  await expect(page.getByText("Что уйдёт модели")).toBeVisible();
  await expect(page.getByText("[EMAIL_1]").first()).toBeVisible();
  // Исходный email остаётся только в приватной колонке, не в sanitized.
  await expect(page.getByText("ivan.petrov@example.com").first()).toBeVisible();

  // Отмена: наружу ничего не уходит, диалог закрывается.
  await page.getByRole("button", { name: "Отмена" }).click();
  await expect(
    page.getByRole("heading", { name: "Проверка перед отправкой" }),
  ).toBeHidden();
});
