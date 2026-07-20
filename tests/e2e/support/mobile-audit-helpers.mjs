import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { expect } from "@playwright/test";

export const MOBILE_VIEWPORTS = Object.freeze([
  { name: "iphone-se", width: 320, height: 568 },
  { name: "iphone-13", width: 390, height: 664 },
  { name: "iphone-15-pro-max", width: 430, height: 739 },
]);

export const MAX_BOTTOM_NAV_VIEWPORT_RATIO = 0.35;

export async function verifyTouchTarget(locator) {
  const boxes = await locator.evaluateAll((elements) =>
    elements
      .filter((element) => !element.hidden && element.getClientRects().length > 0)
      .map((element) => {
        const box = element.getBoundingClientRect();
        return { height: box.height, width: box.width };
      }),
  );
  expect(boxes.length).toBeGreaterThan(0);
  boxes.forEach((box) => {
    expect(box.height).toBeGreaterThanOrEqual(43.5);
    expect(box.width).toBeGreaterThanOrEqual(43.5);
  });
}

export async function scrollToPageMiddle(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const previousBehavior = root.style.scrollBehavior;
    const top = Math.round((root.scrollHeight - window.innerHeight) / 2);
    root.style.scrollBehavior = "auto";
    window.scrollTo({ top, behavior: "auto" });
    root.style.scrollBehavior = previousBehavior;
    return top;
  });
}

export async function verifyMobileViewport(page, { includeNavigation = true } = {}) {
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    viewportHeight: window.innerHeight,
    overflowSources: Array.from(document.querySelectorAll("body *"))
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && (
          box.left < -1 ||
          box.right > window.innerWidth + 1 ||
          element.scrollWidth > element.clientWidth + 1
        );
      })
      .slice(0, 8)
      .map((element) => ({
        className: element.className,
        clientWidth: element.clientWidth,
        overflowX: getComputedStyle(element).overflowX,
        scrollWidth: element.scrollWidth,
        tagName: element.tagName,
        text: element.textContent?.trim().slice(0, 80),
      })),
  }));
  expect(
    layout.scrollWidth,
    `水平溢位來源：${JSON.stringify(layout.overflowSources)}`,
  ).toBeLessThanOrEqual(layout.clientWidth + 1);

  if (!includeNavigation) return;
  const navigation = page.getByRole("navigation", { name: "主要導覽" });
  const box = await navigation.boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(layout.clientWidth + 1);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(layout.viewportHeight + 1);
  await verifyTouchTarget(navigation.getByRole("button"));
  await verifyTouchTarget(page.locator(".app-page.is-active button"));
}

export async function verifyDialogViewport(page) {
  const dialog = page.getByRole("dialog", { name: /登入|建立帳號/u });
  await expect(dialog).toBeVisible();
  const [box, viewport] = await Promise.all([
    dialog.boundingBox(),
    page.evaluate(() => ({ height: window.innerHeight, width: window.innerWidth })),
  ]);
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height + 1);
  expect(await page.evaluate(() => {
    const active = document.activeElement;
    return Boolean(active && document.querySelector("[data-auth-dialog]")?.contains(active));
  })).toBe(true);
  await verifyTouchTarget(dialog.getByRole("button"));
  await verifyMobileViewport(page, { includeNavigation: false });
}

export async function verifyLastContentClearsNavigation(page) {
  await page.evaluate(() => {
    const scrollingElement = document.scrollingElement;
    if (scrollingElement) scrollingElement.scrollTop = scrollingElement.scrollHeight;
  });
  await expect.poll(() => page.evaluate(() => {
    const scrollingElement = document.scrollingElement;
    if (!scrollingElement) return Number.POSITIVE_INFINITY;
    return Math.abs(
      scrollingElement.scrollTop + window.innerHeight - scrollingElement.scrollHeight,
    );
  })).toBeLessThanOrEqual(2);
  const layout = await page.evaluate(() => {
    const activePage = document.querySelector(".app-page.is-active");
    const navigation = document.querySelector(".bottom-nav");
    return {
      navigationTop: navigation?.getBoundingClientRect().top ?? null,
      pageBottom: activePage?.getBoundingClientRect().bottom ?? null,
    };
  });
  expect(layout.pageBottom).not.toBeNull();
  expect(layout.navigationTop).not.toBeNull();
  expect(layout.pageBottom).toBeLessThanOrEqual(layout.navigationTop + 2);
}

export async function captureViewport(page, testInfo, name, options) {
  await verifyMobileViewport(page, options);
  const auditDirectory = join(process.cwd(), "artifacts", "mobile-ui-audit");
  await mkdir(auditDirectory, { recursive: true });
  const projectName = testInfo.project.name.replaceAll(/[^a-z0-9-]/giu, "-");
  const screenshotPath = join(auditDirectory, `${name}-${projectName}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  await testInfo.attach(name, {
    path: screenshotPath,
    contentType: "image/png",
  });
}
