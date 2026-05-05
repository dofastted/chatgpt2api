<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

## Subagents

- ALWAYS wait for all subagents to complete before yielding.
- Spawn subagents automatically when:
  - Parallelizable work (e.g., install + verify, npm test + typecheck, multiple tasks from plan)
  - Long-running or blocking tasks where a worker can run independently.
  - Isolation for risky changes or checks

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## 本仓库追加约束

- 先读 `llmdoc/index.md`、`llmdoc/startup.md`、`llmdoc/must/*`，再读任务相关架构文档。碰到生图卡住、`low quality text render`、代理 `10808` 报错、或发布分支判断，补读 `llmdoc/memory/reflections/2026-05-05-image-proxy-review-boundaries.md`。
- 只要任务和生图链路有关，不要恢复后端文字质量审查。无输入图 prompt 原样下发；下载完成后不做本地 `low quality text render` 复核；`low quality text render` 不能作为本地阻拦用户 prompt 或结果的理由。
- 看到 `curl: (7) Failed to connect ... 10808`，先按本机 Clash 或代理瞬时连接失败处理。先测代理连通性，再决定是否按短退避重试；不要先归因成文字质量审查问题或账号质量问题。
- 发布边界以 `fork/main` 为当前稳定目标。`origin/main` 和本地 `main` 已严重分叉；除非用户明确要求处理上游分叉，不要直接推 `origin/main`，也不要强推 `origin/main`。
- Git 操作继续用 Windows Git。遇到 Git 代理失败，可对单条命令临时加 `-c http.proxy= -c https.proxy=` 直连，不改全局 Git 配置。
