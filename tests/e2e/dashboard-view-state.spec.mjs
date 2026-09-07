import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const fileA = "拆文库/盘龙/dashboard-view-a.md";
const fileB = "拆文库/盘龙/dashboard-view-b.md";
const original = "# 状态恢复\n\n这是磁盘上的正文。\n";
const documentUrl = (file, mode = "edit") => `/?${new URLSearchParams({ file, mode })}`;

test.beforeEach(async ({ request }) => {
  const { workspace } = await (await request.get("/api/workspace")).json();
  await writeFile(resolve(workspace.path, fileA), original);
  await writeFile(resolve(workspace.path, fileB), "# 另一份文稿\n");
});

test.afterEach(async ({ request }) => {
  const { workspace } = await (await request.get("/api/workspace")).json();
  await Promise.all([fileA, fileB].map((file) => rm(resolve(workspace.path, file), { force: true })));
});

test("@mobile 刷新和重新进入恢复视图、文件、模式及行号偏好，显式链接优先", async ({ page }) => {
  await page.goto(documentUrl(fileA));
  await expect(page.locator("#editorInput")).toHaveValue(original);
  await page.getByRole("button", { name: "预览", exact: true }).click();
  await page.locator("#lineNumbersButton").click();
  // 文件所属集合与当前侧栏视图可以不同，恢复时应分别保留。
  if (await page.locator("#mobileBackButton").isVisible()) {
    await page.locator("#mobileBackButton").click();
  }
  await page.locator("#projectsTab").click();
  for (const navigate of [() => page.reload(), () => page.goto("/")]) {
    await navigate();
    await expect(page.locator("#previewPane")).toBeVisible();
    await expect(page.locator("#previewPane")).toContainText("这是磁盘上的正文");
    await expect(page.locator("#projectsTab")).toHaveAttribute("aria-selected", "true");
    await expect(page.locator("#lineNumbersButton")).toHaveAttribute("aria-pressed", "false");
  }
  await page.goto(documentUrl(fileB));
  await expect(page.locator("#editorInput")).toBeVisible();
  await expect(page.locator("#editorTitle")).toHaveText("dashboard-view-b.md");
  await expect(page.locator("#librariesTab")).toHaveAttribute("aria-selected", "true");

  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#deleteButton").click();
  await expect(page.locator("#toastRegion")).toContainText("已删除");
  await expect(page.locator("#editorWorkspace")).toBeHidden();
  await expect(page.locator("#fileTree")).toBeVisible();
  expect(new URL(page.url()).searchParams.has("file")).toBe(false);
  await page.reload();
  await expect(page.locator("#connectionStatus")).toContainText("仅本机");
  await expect(page.locator("#editorWorkspace")).toBeHidden();
  await expect(page.locator("#toastRegion")).not.toContainText("不存在");
});

test("目录刷新和取消切换保留未保存正文，状态记忆只保存位置", async ({ page, context }) => {
  await page.goto(documentUrl(fileA));
  await expect(page.locator("#editorInput")).toHaveValue(original);
  const draft = `${original}未保存的改动`;
  await page.locator("#editorInput").fill(draft);
  await page.locator("#refreshButton").click();
  await expect(page.locator("#toastRegion")).toContainText("工作区目录已刷新");
  await expect(page.locator("#editorInput")).toHaveValue(draft);
  await expect(page.locator("#dirtyStatus")).toContainText("待保存");
  let dismissed = false;
  page.once("dialog", async (dialog) => {
    dismissed = true;
    await dialog.dismiss();
  });
  await page.locator(`.file-row[data-path='${fileB}']`).click();
  expect(dismissed).toBe(true);
  await expect(page.locator("#editorInput")).toHaveValue(draft);
  expect(new URL(page.url()).searchParams.get("file")).toBe(fileA);
  await page.getByRole("button", { name: "预览", exact: true }).click();
  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  expect(stored).not.toContain("未保存的改动");
  const reopened = await context.newPage();
  await reopened.goto("/");
  await expect(reopened.locator("#previewPane")).toBeVisible();
  await expect(reopened.locator("#previewPane")).not.toContainText("未保存的改动");
  await reopened.close();
});

test("工作区隔离、损坏状态和失效文件均可正常恢复到可用页面", async ({ page, request }) => {
  const data = await (await request.get("/api/workspace")).json();
  const key = `story_dashboard_view:${data.workspace.path}`;
  await page.goto(documentUrl(fileA));
  await expect(page.locator("#editorInput")).toHaveValue(original);
  await page.route("**/api/workspace", (route) => route.fulfill({
    json: { ...data, workspace: { ...data.workspace, path: `${data.workspace.path}/another-workspace` } },
  }));
  await page.goto("/");
  await expect(page.locator("#editorEmpty")).toBeVisible();
  await expect(page.locator("#connectionStatus")).toContainText("仅本机");
  await page.unroute("**/api/workspace");

  await page.evaluate((key) => localStorage.setItem(key, "{broken"), key);
  await page.goto("/");
  await expect(page.locator("#editorEmpty")).toBeVisible();
  await page.evaluate((key) => localStorage.setItem(key, JSON.stringify({
    file: "拆文库/盘龙/不存在的文稿.md", view: "invalid", mode: "invalid",
  })), key);
  await page.goto("/");
  await expect(page.locator("#toastRegion")).toContainText("不存在");
  await expect(page.locator("#editorEmpty")).toBeVisible();
  await expect.poll(() => page.evaluate((key) => JSON.parse(localStorage.getItem(key)).file, key)).toBeNull();
  expect(new URL(page.url()).searchParams.has("file")).toBe(false);
  await page.locator(`.file-row[data-path='${fileA}']`).click();
  await expect(page.locator("#editorInput")).toHaveValue(original);
});

test("禁用 localStorage 时仍能使用文件链接和行号", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("blocked", "SecurityError"); } });
  });
  await page.goto(documentUrl(fileA, "preview"));
  await expect(page.locator("#previewPane")).toContainText("状态恢复");
  await page.locator("#lineNumbersButton").click();
  await page.reload();
  await expect(page.locator("#previewPane")).toBeVisible();
  expect(errors).toEqual([]);
});

test("@mobile 行号随中文长段、空行和滚动对齐，预览保留源文件行号", async ({ page }, testInfo) => {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(documentUrl(fileA));
  await expect(page.locator("#editorInput")).toHaveValue(original);
  const mixed = "中文折行 test_with_a_long_word_without_spaces 😀\t".repeat(12);
  const content = Array.from({ length: 40 }, (_, index) => index % 3 ? mixed : "").join("\n") + "\n";
  await page.locator("#editorInput").fill(content);
  await expect(page.locator(".gutter-line")).toHaveCount(41);
  const heightDifference = () => page.evaluate(() => {
    const input = document.querySelector("#editorInput");
    const gutter = document.querySelector("#lineNumbersGutter");
    return Math.abs(input.scrollHeight - gutter.scrollHeight);
  });
  await expect.poll(heightDifference).toBeLessThanOrEqual(2);
  await page.locator("#editorInput").press(process.platform === "darwin" ? "Meta+End" : "Control+End");
  // 显式滚动也覆盖浏览器与宿主系统快捷键不同的情况。
  await page.locator("#editorInput").evaluate((input) => { input.scrollTop = input.scrollHeight; });
  await expect.poll(() => page.evaluate(() => Math.abs(
    document.querySelector("#editorInput").scrollTop - document.querySelector("#lineNumbersGutter").scrollTop,
  ))).toBeLessThanOrEqual(2);
  if (testInfo.project.name === "chromium") {
    await page.setViewportSize({ width: 900, height: 700 });
    await expect.poll(heightDifference).toBeLessThanOrEqual(2);
  }
  await page.locator("#lineNumbersButton").click();
  await expect(page.locator("#lineNumbersGutter")).toBeHidden();
  await page.locator("#lineNumbersButton").click();
  await expect.poll(heightDifference).toBeLessThanOrEqual(2);
  const markdown = "# 标题\n\n一段正文。\n- 项目\n> 引用\n```txt\n示例\n```\n\n尾声";
  await page.locator("#editorInput").fill(markdown);
  await page.getByRole("button", { name: "预览", exact: true }).click();
  expect(await page.locator("#previewPane [data-line]").evaluateAll((nodes) => nodes.map((node) => node.dataset.line)))
    .toEqual(["1", "3", "4", "5", "6", "10"]);
  await expect(page.locator("#previewPane pre")).toHaveText("示例");
  await page.screenshot({ path: testInfo.outputPath("preview-line-numbers.png") });
  expect(errors).toEqual([]);
});
