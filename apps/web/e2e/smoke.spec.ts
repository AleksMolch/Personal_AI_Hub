import { test, expect } from "@playwright/test";

/**
 * E2E smoke: вход администратора и навигация по основным разделам.
 *
 * Предусловие: запущенный стек (http://localhost:3000) и существующий
 * администратор admin / supersecret123 (создаётся через «Первый запуск»).
 */

test("вход и навигация по разделам", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();

  // После входа происходит переход на страницу провайдеров.
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();

  const sections: [string, string][] = [
    ["/chat", "Чат"],
    ["/models", "Модели и цены"],
    ["/usage", "Расходы"],
    ["/jobs", "Задачи"],
    ["/knowledge", "Базы знаний"],
    ["/tables", "Таблицы"],
  ];

  for (const [path, heading] of sections) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
});
