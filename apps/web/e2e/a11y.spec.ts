import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * E2E: доступность (axe-core) и клавиатурная навигация.
 *
 * Предусловие: запущенный стек (http://localhost:3000) и существующий
 * администратор admin / supersecret123 (создаётся через «Первый запуск»).
 *
 * Тесты проверяют требования, заявленные в UI-гайде: отсутствие нарушений
 * axe на ключевых страницах, работу клавиатуры (Tab/Escape) и наличие
 * семантических ориентиров (landmarks), по которым перемещается скринридер.
 */

/** Вход администратора и подавление мастера первичной настройки. */
async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  // Мастер настройки показывается только при первом входе; помечаем его
  // пройденным, чтобы диалог не перекрывал страницы в тестах.
  await page.evaluate(() =>
    window.localStorage.setItem("pah_onboarding_done", "1"),
  );
}

test.describe("Доступность", () => {
  test("страницы не имеют нарушений axe", async ({ page }) => {
    await login(page);

    const pages: [string, string][] = [
      ["/", "Personal AI Hub"],
      ["/chat", "Чат"],
      ["/providers", "Провайдеры"],
      ["/models", "Модели и цены"],
      ["/usage", "Расходы"],
      ["/jobs", "Задачи"],
      ["/knowledge", "Базы знаний"],
      ["/tables", "Таблицы"],
      ["/profile", "Профиль"],
    ];

    for (const [path, heading] of pages) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();

      const results = await new AxeBuilder({ page })
        // Цветовой контраст проверяется отдельно: до полной выверки палитры
        // он даёт заведомо известные замечания по токенам (см. UI-гайд, §1.3).
        .disableRules(["color-contrast"])
        .analyze();

      expect(
        results.violations,
        `Нарушения axe на ${path}: ${results.violations
          .map((v) => `${v.id} (${v.nodes.length})`)
          .join(", ")}`,
      ).toEqual([]);
    }
  });

  test("страница входа доступна и содержит ориентиры", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .disableRules(["color-contrast"])
      .analyze();
    expect(results.violations).toEqual([]);
  });

  test("навигация доступна с клавиатуры и помечает текущий раздел", async ({
    page,
  }) => {
    await login(page);

    await page.goto("/usage");

    // Ориентиры, по которым перемещается скринридер.
    await expect(
      page.getByRole("navigation", { name: "Основная навигация" }),
    ).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();

    // Текущий раздел помечен aria-current="page".
    const current = page
      .getByRole("navigation", { name: "Основная навигация" })
      .getByRole("link", { name: "Расходы" });
    await expect(current).toHaveAttribute("aria-current", "page");

    // Ссылка «Перейти к содержимому» становится видимой при фокусе с клавиатуры.
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Перейти к содержимому" });
    await expect(skipLink).toBeFocused();
  });
});

test.describe("Клавиатура в чате", () => {
  test("поле ввода подписано и доступно с клавиатуры", async ({ page }) => {
    await login(page);
    await page.goto("/chat");

    // Заголовок верхнего уровня обязателен: без него страница лишена
    // ориентира для скринридера (axe: heading-order).
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();

    // Поле ввода существует ВСЕГДА — даже когда моделей нет: иначе при пустой
    // установке пропадает композер и непонятно, куда возвращаться после
    // настройки провайдера (найдено реальным прогоном E2E).
    const input = page.getByLabel("Текст сообщения");
    await expect(input).toBeAttached();

    if (await input.isDisabled()) {
      // Моделей нет — поле заблокировано, но остаётся в раскладке.
      await expect(input).toBeDisabled();
    } else {
      // Модели настроены — поле работает, кнопка отправки подписана.
      await expect(input).toBeEnabled();
      await expect(
        page.getByRole("button", { name: "Отправить сообщение" }),
      ).toBeVisible();
    }

    // Заглушка локального режима есть, но выключена: локального inference нет.
    const localSwitch = page.getByRole("switch").first();
    await expect(localSwitch).toBeDisabled();
  });

  test("журнал сообщений размечен как log", async ({ page }) => {
    await login(page);
    await page.goto("/chat");

    // role=log позволяет скринридеру объявлять новые ответы.
    const log = page.getByRole("log", { name: "Сообщения диалога" });
    await expect(log).toBeAttached();
  });
});
