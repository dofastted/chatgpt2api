# chat-image-compatibility-matrix

迁移目标是保留 `chatgpt2api` 的外部接口，把图片执行路径逐步收进 `services/chat_image/`。

| Endpoint | 当前状态 | 迁移路径 |
|---|---|---|
| `POST /v1/responses` | 保留，Responses 主入口 | 现阶段仍走旧引擎 gateway；后续接 official Responses client |
| `GET /v1/responses/{response_id}` | 保留，读取进程内结果 | 继续读 `RESPONSES_STORE` |
| `POST /v1/response` | 不注册 | 单数路径按 workflow v2 视为无效 |
| `GET /v1/response/{response_id}` | 不注册 | 单数路径按 workflow v2 视为无效 |
| `POST /v1/images/generations` | 保留，兼容入口 | 现阶段经 `ImageGateway.generate_image()` 走旧引擎 |
| `POST /v1/images/edits` | 新增，兼容入口 | multipart 图片转单张输入图后经 `ImageGateway.generate_image()` |
| `GET /v1/models` | 保留 | 当前仍返回 `gpt-image-2` |
| `POST /backend-api/files/process_upload_stream` | 保留 | 本地上传登记与后续 `file_id` 输入图继续使用 |
| `GET /backend-api/my/recent/uploaded_images` | 保留 | 上传记录仍按 Bearer Token 和会话隔离 |
| `GET /backend-api/files/{file_id}/content` | 保留 | 继续读取当前 Bearer Token 的本地上传原图 |
| `GET /api/accounts` / `POST /api/accounts` | 保留 | `POST` 会先规范化单账号或 `accounts[]` 载体 |
| `GET /api/quota` | 保留 | 额度计算不变 |
| `GET /api/image-queue/me` | 保留 | 队列状态不变 |
| user key / redeem code APIs | 保留 | 当前不改 |

当前 gateway 只是 Phase 1 入口收束。`services/chat_image/account_import.py` 已支持单账号 JSON 和 `sub2api` 的 `accounts[]` 载体；`services/chat_image/route_selector.py` 已提供 Free 走 Images、Plus/Pro/Team 走 Responses 的判断，但默认策略仍是 `legacy`，避免隔离 worktree 以外行为变化。
