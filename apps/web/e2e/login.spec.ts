import { test, expect } from "@playwright/test";

/**
 * E2E: вход в приложение.
 *
 * Регрессия на реальный дефект: CORS разрешал только `http://localhost:3000`,
 * поэтому вход по `http://127.0.0.1:3000` молча блокировался браузером —
 * preflight получал 400, а пользователь видел «Не удалось связаться с API».
 * `localhost` и `127.0.0.1` указывают на одну машину, и оба адреса обязаны
 * работать.
 */

const CREDENTIALS = { username: "admin", password: "supersecret123" };

/** Выполняет вход по указанному адресу и проверяет переход к провайдерам. */
async function loginAt(
  page: import("@playwright/test").Page,
  baseUrl: string,
): Promise<void> {
  await page.goto(`${baseUrl}/login`);
  await page.getByLabel("Логин").fill(CREDENTIALS.username);
  await page.getByLabel("Пароль").fill(CREDENTIALS.password);
  await page.getByRole("button", { name: "Войти" }).click();

  // Успешный вход = переход на страницу провайдеров с её заголовком.
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page).toHaveURL(/\/providers$/);
}

test.describe("Вход", () => {
  test("вход по localhost", async ({ page }) => {
    await loginAt(page, "http://localhost:3000");
  });

  test("вход по 127.0.0.1 (CORS: локальный алиас)", async ({ page }) => {
    await loginAt(page, "http://127.0.0.1:3000");
  });

  test("неверный пароль даёт понятную ошибку, а не технический сбой", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByLabel("Логин").fill(CREDENTIALS.username);
    await page.getByLabel("Пароль").fill("wrong-password-123");
    await page.getByRole("button", { name: "Войти" }).click();

    // Сообщение об ошибке выводится в Alert с ролью alert и не содержит
    // текста про сеть: это ошибка аутентификации, а не связи.
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).not.toContainText("связаться с API");
  });
});
