import { test, expect } from "@playwright/test";

/** Временная проверка ресайза панелей чата (удаляется после). */
test("ресайз высоты и ширины", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  await page.getByLabel("Логин").fill("admin");
  await page.getByLabel("Пароль").fill("supersecret123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Провайдеры" })).toBeVisible();
  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Чат" })).toBeAttached();

  const section = page.locator('section[aria-label="Область переписки"]');
  const aside = page.locator('aside[aria-label="Диалоги"]');
  const before = (await section.boundingBox())!;
  const widthBefore = (await aside.boundingBox())!.width;

  // Высота: тянем верхнюю грань вниз — панель должна стать ниже, низ на месте.
  const heightHandle = page.getByRole("button", {
    name: "Изменить высоту панели чата",
  });
  const hb = (await heightHandle.boundingBox())!;
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + 160, { steps: 12 });
  await page.mouse.up();

  const after = (await section.boundingBox())!;
  console.log(
    "HEIGHT",
    JSON.stringify({
      before: Math.round(before.height),
      after: Math.round(after.height),
      bottomBefore: Math.round(before.y + before.height),
      bottomAfter: Math.round(after.y + after.height),
    }),
  );
  expect(after.height).toBeLessThan(before.height - 80);
  expect(
    Math.abs(after.y + after.height - (before.y + before.height)),
  ).toBeLessThan(3);

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
  console.log(
    "WIDTH",
    JSON.stringify({
      before: Math.round(widthBefore),
      after: Math.round(widthAfter),
    }),
  );
  expect(widthAfter).toBeGreaterThan(widthBefore + 80);

  // Двойной клик по ручке высоты возвращает панель на всю высоту.
  await heightHandle.dblclick();
  const restored = (await section.boundingBox())!;
  expect(restored.height).toBeGreaterThan(after.height + 80);

  // На мобильном ручки скрыты.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(heightHandle).toBeHidden();
  await expect(widthHandle).toBeHidden();
});
