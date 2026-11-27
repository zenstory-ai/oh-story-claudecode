# Dashboard 工作台与版本更新

本文件在用户执行工作台启动或版本更新检查时按需读取。

## Dashboard 工作台

用户执行 `/story dashboard`，或明确要求打开工作台、查看项目文件时，启动本地 Dashboard：

1. 默认使用**当前工作目录**；用户明确给出目录时改用该目录，须先确认目录存在。
2. 从当前已加载的 `story` skill 目录定位 `scripts/dashboard-server.mjs`，不硬编码仓库路径、全局 skill 路径或用户主目录。
3. 确认 `node` 可用后，以长运行进程执行：

   ```bash
   node "<story-skill-dir>/scripts/dashboard-server.mjs" --root "<workspace>" --open
   ```

4. 等待输出出现“本机地址”，把完整 URL 回给用户。工具支持后台进程/PTY 时让服务保持运行；无法自动拉起浏览器不算失败，仍返回可点击 URL。
5. Dashboard 默认只监听 `127.0.0.1`。不要主动增加 `--allow-network`，不要把工作区暴露到局域网或公网。

工作台项目识别由 `dashboard-server.mjs` 执行（识别 `拆文库/{书名}/` 及存量 `拆文库-{书名}/`；长篇含 `正文/`、`大纲/`、`设定/`、`追踪/` 任一普通子目录；短篇含 `正文.md` 与 `小节大纲.md`/`设定.md`，或同时含 `设定.md` 与 `小节大纲.md`；不认符号链接与单文件目录）。浏览器支持编辑 `.md`/`.txt`/`.json`/`.yaml`/`.yml`/`.toml`，保存和删除前核对文件内容版本以防覆盖外部修改。

停止服务时终止对应的 Node 进程即可。若用户只问用法，不要代为启动，告知用 `/story dashboard`（按宿主写法替换）。

## 版本更新检查

用户问“有没有新版本”“检查更新”“升级”时执行。**先报告版本，是否安装由用户决定。**

1. **当前版本**：读本 skill 同目录的 `VERSION` 文件；缺失则视为未知。若本 skill 位于写作项目内（如 `skills/`、`.agents/skills/`、`.zcode/skills/`），读到的是项目副本版本。
2. **最新版本**：优先 `gh release view --json tagName,name,url -R zenstory-ai/oh-story-claudecode` 取 `tagName`；无 `gh` 时用 `curl -fsS --max-time 5 https://api.github.com/repos/zenstory-ai/oh-story-claudecode/releases/latest` 取 `.tag_name`（jq 或 grep）。查不到则告知「暂时拉不到最新版本，可手动看 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases)」，不报错。
3. **比较**：当前版本已知时，去掉 `v` 前缀按语义版本（major.minor.patch）比较；未知时只展示最新稳定版，不判定是否最新。`gh release` 默认取 latest 稳定版，不含 pre-release。
4. **告知**：
   - 已最新 → 「已是最新版 vX.Y.Z」。
   - 有新版或当前版本未知 → 展示已知版本与 [Releases](https://github.com/zenstory-ai/oh-story-claudecode/releases) / [CHANGELOG](https://github.com/zenstory-ai/oh-story-claudecode/blob/main/CHANGELOG.md)，有 release notes 时附更新要点，再用宿主提问方式问「现在更新吗？」。选先不则不动，告知随时可再来。
5. **更新**（用户同意后）：按本 skill 目录位置判断安装方式：
   - 插件目录（路径含 `plugins/`）：Claude Code 跑 `claude plugin marketplace update oh-story-skills` 再跑 `claude plugin update oh-story@oh-story-skills`，重启后生效；ZCode 在 Plugin Management 刷新市场后更新 `oh-story`。
   - `npx skills` 安装（全局或当前目录）：重跑 `npx skills add zenstory-ai/oh-story-claudecode -y -g`（当前目录安装的去掉 `-g`）。
   - 其他安装方式（如 ClawHub）：按原方式重装最新版。
   - 写作项目内副本：先按上面对应方式更新安装包，再用新包在项目根运行 `/story-setup` 同步副本；OpenClaw、Reasonix 和通用文件模式需用新包手动覆盖项目 `skills/` 下的 14 个 skill 目录。

   更新完提示：已部署项目在项目根重跑 `/story-setup` 同步 hooks、agents 和参考资料，然后**新开一个会话**，写作助手才会重新加载。
