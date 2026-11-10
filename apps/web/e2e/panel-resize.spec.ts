import { test, expect } from "@playwright/test";

/**
 * E2E ресайза панелей чата: высота панели ввода и ширина списка диалогов.
 *
 * Проверяем именно орган управления: тянем верхнюю грань композера (поле
 * промпта растёт) и правую грань сайдбара; на мобильном ручки скрыты.
 */
test("ресайз панели ввода и сайдбара", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Чат" })).toBeAttached();

  const textarea = page.getByLabel("Текст сообщения");
  const aside = page.locator('aside[aria-label="Диалоги"]');
  const inputBefore = (await textarea.boundingBox())!;
  const widthBefore = (await aside.boundingBox())!.width;

  // Высота панели ввода: тянем верхнюю грань вверх — поле промпта растёт.
  const inputHandle = page.getByRole("separator", {
    name: "Изменить высоту панели ввода",
  });
  const hb = (await inputHandle.boundingBox())!;
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + hb.width / 2, hb.y - 120, { steps: 12 });
  await page.mouse.up();

  const inputAfter = (await textarea.boundingBox())!;
  expect(inputAfter.height).toBeGreaterThan(inputBefore.height + 80);

  // Ширина: тянем правую грань сайдбара вправо.
  const widthHandle = page.getByRole("separator", {
    name: "Изменить ширину панели диалогов",
  });
  const wb = (await widthHandle.boundingBox())!;
  await page.mouse.move(wb.x + wb.width / 2, wb.y + wb.height / 2);
  await page.mouse.down();
  await page.mouse.move(wb.x + 120, wb.y + wb.height / 2, { steps: 12 });
  await page.mouse.up();

  const widthAfter = (await aside.boundingBox())!.width;
  expect(widthAfter).toBeGreaterThan(widthBefore + 80);

  // Двойной клик по ручке высоты возвращает поле к размеру по умолчанию.
  await inputHandle.dblclick();
  const inputRestored = (await textarea.boundingBox())!;
  expect(inputRestored.height).toBeLessThan(inputAfter.height - 80);

  // На мобильном ручки скрыты: там панель занимает всю ширину.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(inputHandle).toBeHidden();
  await expect(widthHandle).toBeHidden();
});
