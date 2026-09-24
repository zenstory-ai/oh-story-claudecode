#!/usr/bin/env node
// opencode-mock-llm.mjs — 给真实 OpenCode 2.x 运行时测试用的 OpenAI 兼容 mock 模型。
//
// 行为：带 tools 的首轮请求按 MOCK_SCRIPT 文件里的 JSON 数组 [{name, arguments}] 一次性发出工具调用
// （每个请求现读，测试可在两次 `opencode run` 之间换剧本而不重启 mock；文件缺失即不调工具）；
// 消息里已有工具结果的轮次回复 "done" 结束；不带 tools 的请求（标题生成等）回复一个标题。
// 每个请求体追加写入 MOCK_LOG（JSONL），测试据此读模型实际拿到的工具清单与工具返回内容。
// 启动后把监听端口打到 stdout 第一行；MOCK_PORT 缺省为 0（随机端口）。
import fs from "node:fs"
import http from "node:http"

const log = process.env.MOCK_LOG
const script = process.env.MOCK_SCRIPT
const usage = { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 }

function scriptedToolCalls() {
  let calls = []
  try {
    calls = JSON.parse(fs.readFileSync(script, "utf8"))
  } catch {}
  return calls.map((call, index) => ({
    id: `call_${index}`,
    type: "function",
    function: { name: call.name, arguments: JSON.stringify(call.arguments ?? {}) },
  }))
}

function chunk(delta, finish = null) {
  return {
    id: "chatcmpl-mock",
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: "probe",
    choices: [{ index: 0, delta, finish_reason: finish }],
  }
}

function reply(res, stream, message, finish) {
  if (stream === false) {
    res.writeHead(200, { "content-type": "application/json" })
    res.end(JSON.stringify({
      id: "chatcmpl-mock",
      object: "chat.completion",
      model: "probe",
      usage,
      choices: [{ index: 0, finish_reason: finish, message: { role: "assistant", ...message } }],
    }))
    return
  }
  const chunks = [chunk({ role: "assistant", content: message.content ?? "" })]
  for (const [index, call] of (message.tool_calls ?? []).entries()) chunks.push(chunk({ tool_calls: [{ index, ...call }] }))
  chunks.push({ ...chunk({}, finish), usage })
  res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" })
  for (const item of chunks) res.write(`data: ${JSON.stringify(item)}\n\n`)
  res.end("data: [DONE]\n\n")
}

const server = http.createServer((req, res) => {
  let raw = ""
  req.on("data", (data) => (raw += data))
  req.on("end", () => {
    let body = {}
    try {
      body = JSON.parse(raw || "{}")
    } catch {}
    if (log) fs.appendFileSync(log, JSON.stringify({ path: req.url, body }) + "\n")
    if (!req.url.includes("/chat/completions")) {
      res.writeHead(404, { "content-type": "application/json" })
      res.end("{}")
      return
    }
    const messages = Array.isArray(body.messages) ? body.messages : []
    const hasTools = Array.isArray(body.tools) && body.tools.length > 0
    const answered = messages.some((message) => message.role === "tool")
    const toolCalls = hasTools && !answered ? scriptedToolCalls() : []
    if (toolCalls.length) {
      reply(res, body.stream, { content: null, tool_calls: toolCalls }, "tool_calls")
    } else {
      reply(res, body.stream, { content: hasTools ? "done" : "Mock title" }, "stop")
    }
  })
})

server.listen(Number(process.env.MOCK_PORT || 0), "127.0.0.1", () => {
  process.stdout.write(`${server.address().port}\n`)
})
