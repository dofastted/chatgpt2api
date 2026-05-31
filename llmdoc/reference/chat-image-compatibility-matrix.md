# chat-image-compatibility-matrix

迁移目标是保留 `chatgpt2api` 的外部接口，把图片执行路径逐步收进 `services/chat_image/`。

| Endpoint | 当前状态 | 迁移路径 |
|---|---|---|
| `POST /v1/responses` | 保留，Responses 主入口 | 经 `BackendService` 选号后按输入图分流；无输入图默认走 Images，上游为 `/backend-api/f/conversation`；Plus/Pro/Team 带输入图走 `/backend-api/codex/responses` |
| `GET /v1/responses/{response_id}` | 保留，读取本服务保存过的结果 | 优先读进程内 `RESPONSES_STORE`，未命中时回退 SQLite response 记录；容器重启后仍可读取已持久化 response |
| `POST /v1/response` | 不注册 | 单数路径按 workflow v2 视为无效 |
| `GET /v1/response/{response_id}` | 不注册 | 单数路径按 workflow v2 视为无效 |
| `POST /v1/images/generations` | 保留，第三方客户端兼容入口 | JSON 请求进入 `generate_image_payload`；`response_format=url` 会保存生成图并返回 HTTP 图片 URL |
| `POST /v1/images/edits` | 保留，第三方客户端兼容入口 | multipart 图片转单张 `input_image` 后进入 `generate_image_payload`；`response_format=url` 同样返回 HTTP 图片 URL |
| `GET /v1/models` | 保留 | 当前返回 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K` |
| `POST /backend-api/files/process_upload_stream` | 保留 | 本地上传登记与后续 `file_id` 输入图继续使用 |
| `GET /backend-api/my/recent/uploaded_images` | 保留 | 上传记录仍按 Bearer Token 和会话隔离 |
| `GET /backend-api/files/{file_id}/content` | 保留 | 继续读取当前 Bearer Token 的本地上传原图 |
| `GET /api/accounts` / `POST /api/accounts` | 保留 | `POST` 会先规范化单账号或 `accounts[]` 载体 |
| `GET /api/quota` | 保留 | 额度计算不变 |
| `GET /api/image-queue/me` | 保留 | 继续返回当前请求位置，并带 60 次/60 秒窗口状态 |
| user key / redeem code APIs | 保留 | 当前不改 |

当前 gateway 已接入账号套餐与输入图分流。`services/chat_image/account_import.py` 支持单账号 JSON 和 `sub2api` 的 `accounts[]` 载体；`services/chat_image/route_selector.py` 负责无输入图走 `images`、Free 输入图走 `images_edit`、Plus/Pro/Team 输入图走 `responses` 的判断；`services/chat_image/gateway.py` 会把 route 继续传给 `services/image_service.py`。公开 Images 入口只做协议兼容，不改变内部账号路线。`IMAGE_ROUTE_POLICY=legacy` 仍可作为回退开关，但默认策略已经是 `plan_type`。
