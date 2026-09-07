import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

async function read(relativePath) {
  return readFile(join(repositoryRoot, relativePath), "utf8");
}

test("Claude Code marketplace exposes the canonical story skill bundle", async () => {
  const marketplace = JSON.parse(await read(".claude-plugin/marketplace.json"));
  const claudeBundle = marketplace.plugins.find((plugin) => plugin.name === "oh-story");
  const manifest = JSON.parse(await read(".claude-plugin/plugin.json"));

  assert.ok(claudeBundle, "Claude Code marketplace must publish the oh-story bundle");
  assert.equal(claudeBundle.source, "./");
  assert.equal(manifest.name, claudeBundle.name);
  assert.equal(manifest.version, claudeBundle.version);
  assert.equal(claudeBundle.skills, undefined, "the catalog must not filter out default skills");
  assert.equal(manifest.skills, undefined, "the bundle uses default skills/ discovery");
  const storySkillRoot = join(repositoryRoot, claudeBundle.source, "skills", "story");

  for (const relativePath of [
    "SKILL.md",
    "scripts/dashboard-server.mjs",
    "assets/index.html",
    "assets/styles.css",
    "assets/app.js",
  ]) {
    const bundled = await stat(join(storySkillRoot, relativePath));
    assert.ok(bundled.isFile(), `${relativePath} must ship inside the canonical story skill`);
  }
});
