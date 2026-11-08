import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const files = {
  conflict: "拆文库/盘龙/dashboard-edit-conflict.md",
  retry: "拆文库/盘龙/dashboard-edit-retry.md",
  deleteConflict: "拆文库/盘龙/dashboard-delete-conflict.md",
};
const original = "# 编辑安全\n\n磁盘初稿。\n";
const documentUrl = (file) => `/?${new URLSearchParams({ file, mode: "edit" })}`;

let workspacePath;

test.beforeEach(async ({ request }) => {
  const { workspace } = await (await request.get("/api/workspace")).json();
  workspacePath = workspace.path;
  await Promise.all(Object.values(files).map((file) => writeFile(resolve(workspacePath, file), original)));
});

test.afterEach(async () => {
  await Promise.all(Object.values(files).map((file) => rm(resolve(workspacePath, file), { force: true })));
});

test("外部修改触发保存冲突，既可保留当前编辑也可重新载入磁盘版本", async ({ page, request }) => {
  await page.goto(documentUrl(files.conflict));
  await expect(page.locator("#editorInput")).toHaveValue(original);

  const draft = `${original}\nDashboard 中尚未保存的改动。`;
  const external = "# 外部程序的新版本\n\n磁盘内容不能被旧版本覆盖。\n";
  await page.locator("#editorInput").fill(draft);
  await writeFile(resolve(workspacePath, files.conflict), external);
  await page.locator("#saveButton").click();

  const conflictDialog = page.locator("#conflictDialog");
  await expect(conflictDialog).toBeVisible();
  await expect(page.locator("#editorInput")).toHaveValue(draft);
  await expect(page.locator("#dirtyStatus")).toContainText("待保存");
  expect((await (await request.get(`/api/file?path=${encodeURIComponent(files.conflict)}`)).json()).content)
    .toBe(external);

  await conflictDialog.getByRole("button", { name: "保留当前编辑" }).click();
  await expect(conflictDialog).toBeHidden();
  await expect(page.locator("#editorInput")).toHaveValue(draft);
  await expect(page.locator("#saveButton")).toBeEnabled();

  await page.locator("#saveButton").click();
  await expect(conflictDialog).toBeVisible();
  await conflictDialog.getByRole("button", { name: "重新载入磁盘版本" }).click();
  await expect(conflictDialog).toBeHidden();
  await expect(page.locator("#editorInput")).toHaveValue(external);
  await expect(page.locator("#dirtyStatus")).toContainText("已保存");
  await expect(page.locator("#saveButton")).toBeDisabled();
});

test("保存接口暂时失败时保留草稿，下一次重试可以正常落盘", async ({ page, request }) => {
  let failedOnce = false;
  await page.route("**/api/file", async (route) => {
    if (route.request().method() === "PUT" && !failedOnce) {
      failedOnce = true;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: { code: "temporary_failure", message: "模拟的临时保存失败" } }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto(documentUrl(files.retry));
  const draft = `${original}\n网络恢复后应当成功保存。`;
  await page.locator("#editorInput").fill(draft);
  await page.locator("#saveButton").click();

  await expect(page.locator("#toastRegion")).toContainText("模拟的临时保存失败");
  await expect(page.locator("#editorInput")).toHaveValue(draft);
  await expect(page.locator("#dirtyStatus")).toContainText("待保存");
  await expect(page.locator("#saveButton")).toBeEnabled();
  expect((await (await request.get(`/api/file?path=${encodeURIComponent(files.retry)}`)).json()).content)
    .toBe(original);

  await page.locator("#saveButton").click();
  await expect(page.locator("#dirtyStatus")).toContainText("已保存");
  await expect(page.locator("#toastRegion")).toContainText("已保存《dashboard-edit-retry.md》");
  expect((await (await request.get(`/api/file?path=${encodeURIComponent(files.retry)}`)).json()).content)
    .toBe(draft);
});

test("外部修改后的文件拒绝删除，并保留磁盘新版本和当前编辑界面", async ({ page, request }) => {
  await page.goto(documentUrl(files.deleteConflict));
  await expect(page.locator("#editorInput")).toHaveValue(original);

  const external = "# 删除前的外部更新\n\n这个新版本必须保留。\n";
  await writeFile(resolve(workspacePath, files.deleteConflict), external);
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#deleteButton").click();

  await expect(page.locator("#toastRegion")).toContainText("重新载入后再删除");
  await expect(page.locator("#editorWorkspace")).toBeVisible();
  await expect(page.locator("#editorInput")).toHaveValue(original);
  await expect(page.locator("#deleteButton")).toBeEnabled();
  const persisted = await request.get(`/api/file?path=${encodeURIComponent(files.deleteConflict)}`);
  expect(persisted.status()).toBe(200);
  expect((await persisted.json()).content).toBe(external);
});
