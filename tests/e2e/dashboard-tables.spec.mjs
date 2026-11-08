import { rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const files = {
  lf: "拆文库/盘龙/dashboard-table-lf.md",
  crlf: "拆文库/盘龙/dashboard-table-crlf.md",
  boundaries: "拆文库/盘龙/dashboard-table-boundaries.md",
};

const wideHeader = ["左对齐", "居中", "右对齐", ...Array.from({ length: 9 }, (_, index) => `宽列${index + 1}`)];
const wideDivider = [":---", ":---:", "---:", ...Array.from({ length: 9 }, () => "---")];
const wideRow = [
  "**粗体**",
  "`甲\\|乙`",
  "文本\\|竖线",
  "<img src=x onerror=alert(1)>",
  ...Array.from({ length: 8 }, (_, index) => `这是用于验证窄屏横向滚动的中文长单元格${index + 1}`),
];
const wideRow2 = wideHeader.map((_, index) => `第二行${index + 1}`);
const wideTable = [
  "# 表格预览",
  "",
  `| ${wideHeader.join(" | ")} |`,
  `| ${wideDivider.join(" | ")} |`,
  `| ${wideRow.join(" | ")} |`,
  `| ${wideRow2.join(" | ")} |`,
  "",
].join("\n");

const boundaryMarkdown = [
  "普通段落 | 即使含有竖线也不是表格",
  "",
  "| 失配表头 | 第二列 |",
  "| --- |",
  "| 不应 | 渲染 |",
  "",
  "```md",
  "| 代码 | 围栏 |",
  "| --- | --- |",
  "| 保持 | 原文 |",
  "```",
  "",
  "名称 | 数量 | 备注",
  ":- | :-: | ---:",
  "短行 | 1",
  "长行 | 2 | 保留 | 丢弃",
  "## 紧邻标题 | 不是数据行",
  "- 紧邻列表 | 也不是数据行",
].join("\n");

const documentUrl = (file) => `/?${new URLSearchParams({ file, mode: "preview" })}`;

test.beforeEach(async ({ request }) => {
  const { workspace } = await (await request.get("/api/workspace")).json();
  await Promise.all([
    writeFile(resolve(workspace.path, files.lf), wideTable),
    writeFile(resolve(workspace.path, files.crlf), wideTable.replaceAll("\n", "\r\n")),
    writeFile(resolve(workspace.path, files.boundaries), boundaryMarkdown),
  ]);
});

test.afterEach(async ({ request }) => {
  const { workspace } = await (await request.get("/api/workspace")).json();
  await Promise.all(Object.values(files).map((file) => rm(resolve(workspace.path, file), { force: true })));
});

test("@mobile LF 和 CRLF 表格保留语义、行号、内联格式及窄屏布局", async ({ page }, testInfo) => {
  for (const file of [files.lf, files.crlf]) {
    await page.goto(documentUrl(file));
    const preview = page.locator("#previewPane");
    const table = preview.locator("table");
    await expect(table).toHaveCount(1);
    await expect(table.locator("thead th")).toHaveCount(wideHeader.length);
    await expect(table.locator("tbody tr")).toHaveCount(2);
    await expect(table.locator("tbody tr").first().locator("td")).toHaveCount(wideHeader.length);
    await expect(table.locator("strong")).toHaveText("粗体");
    await expect(table.locator("code")).toHaveText("甲|乙");
    await expect(table.locator("tbody tr").first().locator("td").nth(2)).toHaveText("文本|竖线");
    await expect(table).toContainText("<img src=x onerror=alert(1)>");
    await expect(table.locator("img")).toHaveCount(0);
    expect(await table.locator("[data-line]").evaluateAll((nodes) => nodes.map((node) => node.dataset.line)))
      .toEqual(["3", "5", "6"]);

    const alignments = await table.locator("tbody tr").first().locator("td").evaluateAll((cells) =>
      cells.slice(0, 3).map((cell) => getComputedStyle(cell).textAlign));
    expect(alignments).toEqual(["left", "center", "right"]);

    const layout = await table.evaluate((element) => {
      const scroller = element.parentElement;
      const previewPane = document.querySelector("#previewPane");
      return {
        overflowX: getComputedStyle(scroller).overflowX,
        scrollerClientWidth: scroller.clientWidth,
        scrollerScrollWidth: scroller.scrollWidth,
        previewClientWidth: previewPane.clientWidth,
        previewScrollWidth: previewPane.scrollWidth,
      };
    });
    expect(layout.overflowX).toBe("auto");
    expect(layout.scrollerScrollWidth).toBeGreaterThan(layout.scrollerClientWidth);
    expect(layout.previewScrollWidth).toBeLessThanOrEqual(layout.previewClientWidth + 1);

    const tableColors = () => table.locator("th").first().evaluate((cell) => ({
      backgroundColor: getComputedStyle(cell).backgroundColor,
      borderColor: getComputedStyle(cell).borderColor,
    }));
    const colorScheme = () => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
    if (await colorScheme() === "dark") await page.locator("#themeButton").click();
    await expect.poll(colorScheme).toBe("light");
    const light = await tableColors();
    expect(light.backgroundColor).not.toBe("rgba(0, 0, 0, 0)");
    expect(light.borderColor).not.toBe("rgba(0, 0, 0, 0)");
    if (file === files.lf) {
      await page.screenshot({
        path: testInfo.outputPath(`table-${testInfo.project.name}-light.png`),
        fullPage: true,
      });
    }
    await page.locator("#themeButton").click();
    await expect.poll(colorScheme).toBe("dark");
    const dark = await tableColors();
    expect(dark.backgroundColor).not.toBe(light.backgroundColor);
    expect(dark.borderColor).not.toBe("rgba(0, 0, 0, 0)");
    if (file === files.lf) {
      await page.screenshot({
        path: testInfo.outputPath(`table-${testInfo.project.name}-dark.png`),
        fullPage: true,
      });
    }
  }
});

test("只识别有效表格，代码围栏和普通竖线保留原文，异常行按表头列数归一", async ({ page }) => {
  await page.goto(documentUrl(files.boundaries));
  const preview = page.locator("#previewPane");
  await expect(preview.locator("table")).toHaveCount(1);
  await expect(preview.locator("p").first()).toHaveText("普通段落 | 即使含有竖线也不是表格");
  await expect(preview).toContainText("| 失配表头 | 第二列 |");
  await expect(preview.locator("pre")).toHaveText([
    "| 代码 | 围栏 |",
    "| --- | --- |",
    "| 保持 | 原文 |",
  ].join("\n"));

  const table = preview.locator("table");
  await expect(table.locator("th")).toHaveText(["名称", "数量", "备注"]);
  await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["短行", "1", ""]);
  await expect(table.locator("tbody tr").nth(1).locator("td")).toHaveText(["长行", "2", "保留"]);
  await expect(table.locator("tbody tr")).toHaveCount(2);
  await expect(preview.locator("h2")).toHaveText("紧邻标题 | 不是数据行");
  await expect(preview.locator("li")).toHaveText("紧邻列表 | 也不是数据行");
});
