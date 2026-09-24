import type { Plugin } from "@opencode/plugin"
import * as fs from "node:fs"
import * as path from "node:path"
import { execSync } from "node:child_process"
import {
  discoverActiveBook,
  resolveTarget,
  extractProseTargets,
  extractPatchTargets,
  proseBlockReason,
  proseAfterWrite,
} from "./lib/story_hook_core.js"

// 只支持 OpenCode 2.x 插件 API（default export `{ id, setup }`）。1.x 的 loader 读不了这个形状，
// 会记一行 "failed to load plugin" 后继续跑——守卫整场静默失效，所以 story-setup 部署前先查版本。
//
// 写正文守卫的检测逻辑（去 AI 味轻量确定性网、大纲/细纲守卫、字数/落盘/标题去重、
// 正文写入目标抽取）与 ZCode hook 共享同一份 story_hook_core.js，随本插件一起部署到
// .opencode/plugins/lib/story_hook_core.js。放 lib/ 子目录而非平铺：plugins/ 下每个 .ts/.js 都会被
// 当成插件加载；子目录只有含 server.* / index.* / tui.* / rpc.* 入口时才算插件包，lib/ 里不得放这些
// 文件名。这里只保留 OpenCode 宿主相关的部分：项目根定位、事件模型（tool execute.before/after、
// session compaction）、以及把发现追加进写工具返回内容的输出信封。
// 共享核以 bash hook 为 oracle，parity 由 test-prose-net-parity.sh 守卫。

type ToolInput = Record<string, unknown>
type TextPart = { type: "text"; text: string }

// 2.x 的后台服务一个进程服务多个项目，process.cwd() 不是用户项目：一切路径都以插件所在
// location（ctx.location.directory，会话工作目录）为起点。项目根是它的 git toplevel。
function projectRoot(directory: string): string {
  try {
    return execSync("git rev-parse --show-toplevel", {
      cwd: directory,
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim()
  } catch {
    return directory
  }
}

// 相对路径的解析起点：工具自带 workdir（shell）时按会话目录解析它，且不得逃出项目根；否则就是会话目录。
function targetBase(root: string, directory: string, input: ToolInput): string {
  const raw = input.workdir
  if (typeof raw !== "string" || !raw.trim()) return directory
  let candidate = path.resolve(directory, raw)
  let canonicalRoot = path.resolve(root)
  try {
    if (!fs.statSync(candidate).isDirectory()) return directory
    candidate = fs.realpathSync(candidate)
    canonicalRoot = fs.realpathSync(root)
  } catch {
    return directory
  }
  const relative = path.relative(canonicalRoot, candidate)
  return relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)
    ? directory
    : candidate
}

function tryGit(root: string, args: string): string {
  try {
    return execSync(`git ${args}`, {
      cwd: root,
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    }).trim()
  } catch {
    return ""
  }
}

function asInput(value: unknown): ToolInput {
  return value && typeof value === "object" ? (value as ToolInput) : {}
}

function text(input: ToolInput, key: string): string {
  const value = input[key]
  return typeof value === "string" ? value : ""
}

// 文件变更类工具的落盘目标。patch 是 edit 类工具（permission 与 write/edit 同为 edit），
// 部分模型只暴露它、隐藏 write/edit——不接这个分支等于守卫整场失效。目标抽取（*** Add/Update File:
// 与 *** Move to: 的目的地）复用共享核，与 ZCode/Codex adapter 同一份判据；Move 必须走目的地，
// 否则搬家式补丁能把无细纲草稿搬进 正文/。
function mutationTargets(tool: string, input: ToolInput): string[] {
  if (tool === "write" || tool === "edit") {
    const filePath = text(input, "path")
    return filePath ? [filePath] : []
  }
  if (tool === "patch") return extractPatchTargets(text(input, "patchText"))
  return []
}

function preCompactOutput(directory: string): string {
  const root = projectRoot(directory)
  const lines = ["=== Pre-Compact Summary ==="]
  const bookDir = discoverActiveBook(root)
  if (bookDir) {
    const ctxPath = path.join(bookDir, "追踪", "上下文.md")
    if (fs.existsSync(ctxPath)) {
      const lineCount = fs.readFileSync(ctxPath, "utf-8").split("\n").length
      const relPath = path.relative(root, ctxPath)
      lines.push(`Writing context: ${relPath} (${lineCount} lines)`)
    } else {
      lines.push("Active state: not found")
    }
  } else {
    lines.push("Active state: not found")
  }

  const changed = tryGit(root, "diff --name-only")
  const staged = tryGit(root, "diff --name-only --cached")
  const changedCount = changed ? changed.split("\n").filter(Boolean).length : 0
  const stagedCount = staged ? staged.split("\n").filter(Boolean).length : 0
  lines.push(`Git: ${changedCount} unstaged, ${stagedCount} staged`)

  lines.push("=== Pre-Compact Complete ===")
  return lines.join("\n")
}

// 把发现追加到模型读到的工具返回内容后面。content 缺省时 OpenCode 会把 output 序列化成文本给模型，
// 这里照同一规则补齐再追加，不吞掉原结果。
function appendNote(
  result: { content?: string | ReadonlyArray<unknown>; output?: unknown },
  note: string
): string | ReadonlyArray<unknown> {
  const content = result.content
  if (typeof content === "string") return `${content}\n\n${note}`
  const base: ReadonlyArray<unknown> =
    content && content.length > 0
      ? content
      : [{ type: "text", text: typeof result.output === "string" ? result.output : JSON.stringify(result.output ?? "") }]
  return [...base, { type: "text", text: note } satisfies TextPart]
}

export default {
  id: "oh-story.story-hooks",
  async setup(ctx) {
    const directory = ctx.location.directory

    // 压缩前把当前写作上下文位置写进摘要请求的 system，摘要才会带上「接着写哪本、状态文件在哪」。
    // OpenCode 无压缩后 hook，不注入 post-compact 信息。
    await ctx.session.hook("compaction", (event) => {
      const preMsg = preCompactOutput(directory)
      if (preMsg) event.system.push({ type: "text", text: preMsg })
    })

    await ctx.tool.hook("execute.before", (event) => {
      const input = asInput(event.input)
      const targets =
        event.tool === "shell" ? extractProseTargets(text(input, "command")) : mutationTargets(event.tool, input)

      // 非写类工具（read/grep/glob/…）到这里 targets 为空直接返回：projectRoot() 是同步 execSync，
      // 插件常驻在 OpenCode 服务进程里，只有确认有目标要查时才 fork git。
      if (targets.length === 0) return

      const root = projectRoot(directory)
      const base = targetBase(root, directory, input)
      for (const target of [...new Set(targets)]) {
        const reason = proseBlockReason(root, resolveTarget(root, target, base))
        if (reason) {
          const source = event.tool === "shell" ? "已从 Shell 命令识别到正文写入目标。" : "已识别到正文写入目标。"
          throw new Error(`${reason}（${source}）`)
        }
      }
    })

    // 正文落盘兜底：写正文后跑轻量确定性网（截断/拒绝语/工程词/复读 + 落盘/字数/标题去重），
    // 把发现追加进写工具的返回内容让模型读到。非正文文件、无发现一律不动结果（静默放行）。
    await ctx.tool.hook("execute.after", (event) => {
      if (event.status !== "completed") return
      const input = asInput(event.input)
      const targets = mutationTargets(event.tool, input)
      if (targets.length === 0) return
      const root = projectRoot(directory)
      const base = targetBase(root, directory, input)
      try {
        const notes: string[] = []
        for (const target of [...new Set(targets)]) {
          const note = proseAfterWrite(root, resolveTarget(root, target, base))
          if (note) notes.push(note)
        }
        if (notes.length) {
          event.result = { ...event.result, content: appendNote(event.result, notes.join("\n\n")) }
        }
      } catch {
        // 兜底不能反过来卡流程：解析失败一律放行
      }
    })
  },
} satisfies Plugin.Plugin
