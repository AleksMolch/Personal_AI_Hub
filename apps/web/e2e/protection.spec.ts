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

test("в локальном режиме веб-переключатель остаётся, но неактивен", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");
  // Ждём загрузки возможностей сервера: и режим, и веб-переключатель
  // появляются из одного ответа capabilities, иначе count() увидит ноль.
  await expect(
    page.getByRole("button", { name: /Режим обработки данных/ }),
  ).toBeVisible();

  const webSwitch = page.getByRole("switch", { name: "Веб" });
  // Веб-поиск может быть выключен на сервере: тогда тумблера нет и проверять
  // нечего. Это не ошибка интерфейса.
  if ((await webSwitch.count()) === 0) {
    test.skip(true, "веб-поиск выключен на сервере (WEB_SEARCH_ENABLED=0)");
  }
  await expect(webSwitch).toBeEnabled();

  // Локальный режим: тумблер не исчезает (строка не «прыгает»), а блокируется.
  await page.getByRole("button", { name: /Режим обработки данных/ }).click();
  await page.getByRole("radio", { name: "Только локально" }).click();
  await expect(webSwitch).toBeVisible();
  await expect(webSwitch).toBeDisabled();

  // Возврат в гибрид снова разрешает поиск на том же месте.
  await page.getByRole("button", { name: /Режим обработки данных/ }).click();
  await page.getByRole("radio", { name: "Защищённый гибрид" }).click();
  await expect(webSwitch).toBeEnabled();
});

test("гибрид: preview с псевдонимами без отправки", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  // Дожидаемся входа: иначе переход на /chat случится раньше сохранения токена.
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");

  // Режим выбирается выпадающим меню в строке композера (как глубина
  // рассуждений): сначала открываем меню, затем выбираем пункт.
  await page.getByRole("button", { name: /Режим обработки данных/ }).click();
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

test("облако: предупреждение о найденной почте можно отменить", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");

  // Режим мог сохраниться в диалоге с прошлого теста: явно возвращаем облако.
  await page.getByRole("button", { name: /Режим обработки данных/ }).click();
  await page.getByRole("radio", { name: "Облако с предупреждениями" }).click();
  await page
    .getByLabel("Текст сообщения")
    .fill("Моя почта ivan.petrov@example.com");
  await page.getByRole("button", { name: "Отправить сообщение" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Перед отправкой в облако")).toBeVisible();
  await expect(dialog.getByText(/E-mail/)).toBeVisible();
  // Отмена: предупреждение закрывается и ничего не отправляется.
  await dialog.getByRole("button", { name: "Отмена" }).click();
  await expect(dialog.getByText("Перед отправкой в облако")).toBeHidden();
});
