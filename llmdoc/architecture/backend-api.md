# backend-api

后端入口是 `services/api.py:187` 的 `create_app`。这里同时做四件事：

- 初始化 `BackendService`，把图片请求交给账号池轮询处理，见 `services/api.py:249`。
- 注册 CORS 中间件，见 `services/api.py:263`。
- 注册业务路由，见 `services/api.py:275` 到 `services/api.py:613`。
- 注册静态文件回退，让导出的前端站点和 API 共用一个进程，见 `services/api.py:540`。

鉴权模型：

- 认证上下文解析在 `services/api.py:100`。
- 普通鉴权在 `services/api.py:192`。
- 管理员鉴权在 `services/api.py:199`。
- `user_key` 的模型单价解析在 `services/api.py:142`，图片模型名校验在 `services/api.py:169`。
- 当前默认单价是 `gpt-image-2=2`、`gpt-image-2-2K=2`、`gpt-image-2-4K=8`，来源在 `services/user_key_service.py` 和 `services/api.py`。
- 图片请求如果走 `user_key`，实际扣费不再是全局固定倍率，而是 `pricing[model] * n`，预扣与回退逻辑在 `services/api.py:481`。
- 图片协议转换也在这一层完成：`build_images_response_payload`、`iter_images_stream`、`build_responses_payload`、`iter_responses_stream` 会把内部结果包成对外接口需要的 JSON 或 SSE。

接口分组：

- 公共信息：`/v1/models`、`/version`，位置在 `services/api.py:273` 与 `services/api.py:293`。
- Response 图片兼容：主入口是 `/v1/responses`、`/v1/responses/{response_id}`，位置在 `services/api.py` 的 Responses 路由段。单数 `/v1/response` 不再注册。
- 图片编辑兼容：`/v1/images/edits` 接收 multipart 图片和 prompt，先转成单张输入图，再复用图片生成队列、账号池和计费路径。
- 本地上传：`/backend-api/files/process_upload_stream`、`/backend-api/my/recent/uploaded_images`、`/backend-api/files/{file_id}/content`，位置在 `services/api.py:859` 到 `services/api.py:913`。
- 登录与会话：`/auth/login`、`/auth/session`，位置在 `services/api.py:283` 与 `services/api.py:288`。
- 账号池：`/api/accounts`、`/api/accounts/refresh`、`/api/accounts/update`，位置在 `services/api.py:297`、`services/api.py:412`、`services/api.py:425`。
- 用户 key：`/api/user-keys`、`/api/user-keys/update`，位置在 `services/api.py:302`、`services/api.py:362`、`services/api.py:388`、`services/api.py:453`。
- 兑换码：`/api/redeem-codes`、`/api/redeem-codes/redeem`，位置在 `services/api.py:302` 之后的管理路由段。
- 额度接口：`/api/quota`，位置在 `services/api.py:399`。
- 图片生成：`/v1/images/generations`，位置在 `services/api.py:558`。
- 公开画廊：`GET /api/gallery/public`、`POST /api/gallery/{item_id}/events`、`POST /api/gallery/submissions`，位置在 `services/api.py` 的 gallery 路由段。
- 管理员画廊：`GET /api/admin/gallery`、`PATCH /api/admin/gallery/{item_id}`、`DELETE /api/admin/gallery/{item_id}`，位置在 `services/api.py` 的 admin gallery 路由段。

协议约定：

- `/v1/responses` 对外按 OpenAI Responses 风格返回 `response.output[]`，图片项类型是 `image_generation_call`。
- Responses 生图的顶层 `model` 应是文本模型，公开图片模型放在 `tools[].model`。API 层会把内部图片结果挂到 `response.output[]`，并保持 `billing.requested_model` 是请求的公开模型。当前如果没传图片模型，默认会落到 `gpt-image-2`，逻辑在 `services/api.py` 的 `resolve_requested_response_image_model`。
- Responses 生图第一版现在支持 `input_text + 单张 input_image`。API 层会校验 `image_url` 只能是 `http(s)` 或 `data:image/*`；如果传的是 `file_id`，会在 `services/api.py:813` 到 `services/api.py:821` 注入当前请求的 `owner_auth_token`，供后续读取本地上传文件。
- 本地上传元数据和文件由 `services/uploaded_image_service.py:63` 到 `services/uploaded_image_service.py:228` 管理，上传记录按 Bearer Token 哈希隔离。
- 上传接口只接收单张图片文件，大小上限 8 MB，返回值里会带 `file_id`、尺寸、大小和 `/backend-api/files/{file_id}/content` 下载地址，逻辑在 `services/api.py:859` 到 `services/api.py:913`。
- `/v1/images/generations`、`/v1/images/edits` 和 `/v1/responses` 现在都会在顶层额外透传 `copied_text`，前提是上游页面正文里真的返回了这段文本，封装点在 `services/api.py`。
- 如果上游没有返回图片但返回了文本，API 不把它当成空结果超时报错。`services/api.py` 会把文本写到顶层 `text_content` 和 `copied_text`；`/v1/responses` 还会追加一个 `message/output_text` 到 `response.output[]`，并保持 `response.completed` 加 `data: [DONE]`。
- 兑换码创建只允许 `20` 或 `100` 两档额度。用户 key 兑换成功后会返回 `added_quota`，并把这次额度加到当前剩余值上，不会重置成固定值。
- `/v1/images/generations` 的流式输出按图片接口风格返回；最终结果一定会给 `image_generation.completed`，然后给 `data: [DONE]`。
- `/v1/responses` 的流式输出按 Responses 接口风格返回；最终结果一定会给 `response.completed`，然后给 `data: [DONE]`。失败会给 `response.failed` 和 `data: [DONE]`，让调用方能结束等待。
- `GET /api/image-queue/me` 是当前 Bearer Token 的队列状态入口，返回等待数、运行数、活动数和可选 `request_id` 的排队位置。前端图片页靠它显示当前用户队列和当前请求进度。
- `GET /api/image-queue/admin` 是管理员队列入口，返回当前所有活动 ticket，不按用户过滤。
- `GET /api/image-requests` 和 `GET /api/image-requests/{request_id}` 是管理员请求记录入口，数据来自 SQLite 表 `image_request_records`。
- 队列状态放在 `services/image_queue_service.py`，只保存在进程内。请求开始前会先登记 ticket，响应真正发完后才结束 ticket。
- 请求轨迹放在 `services/image_request_log_service.py`，会记录 `accepted / waiting / assigning_account / running / finished / failed / rejected` 状态、耗时、扣费和路线摘要。
- 2026-04-26 云端实测 `/v1/responses` 和 `/v1/images/generations` 混合 20 并发时共享同一个 `image_queue_service` 统计：全局运行峰值 20，结束后 `waiting=0`、`running=0`。
- 账号、用户 key、兑换码、代理、上传图元数据和 Responses 历史现在通过 `services/sqlite_store.py` 写入 SQLite；旧 JSON 文件只在对应 SQLite 文档为空时导入一次。
- 公开画廊通过 `services/gallery_service.py` 写入 SQLite 表 `gallery_items` 和 `gallery_assets`。服务发现缺少 `source='seed'` 记录时，会从 `web/src/data/gallery-ui-seed.json` 幂等补导入初始公开项，并跳过 `未提供`、`提示词`、过短闲聊等明显不可用 prompt；已有用户投稿不会阻止 seed 恢复。公开和管理员列表会把旧 `data:image/*;base64,...` 资产替换成 `/api/gallery/assets/{asset_id}`，避免列表 JSON 携带图片正文；该资产读取端点只解码旧 base64 图片内容。
- 公开画廊项记录 `prompt`、`prompt_preview`、图片 assets、状态、可见性、排序、置顶、提交者哈希、审核时间、发布时间、点击数和使用数。用户投稿只保存 owner hash，不保存原始 Bearer Token。
- 公开统计入口只允许 `published` 且 `visibility=1` 的项记录 click/use；`pending`、`rejected`、`hidden` 和 `deleted` 不会被公开端点改动。
- 数据管理接口在 `services/api.py` 注册，底层是 `services/data_management_service.py`。管理员可查看 SQLite 状态、备份记录、设置、S3 测试和日志；普通 key 访问会返回 `403`。
- 图片会话服务端保存入口是 `GET/POST/DELETE /api/image-conversations`，按 Bearer Token 哈希隔离。`image_conversations` 仍保存完整 `payload` 供单条详情读取，同时保存 `summary_payload` 供 `summary=true` 列表读取；列表热路径不再读取完整图片 payload。前端仍保留本地缓存和一次上传旧会话的兼容逻辑。

后台线程：

- 账号远端信息不再自动刷新。启动时不会开账号刷新线程，新增账号和图片请求前也不会访问远端刷新账号信息。
- `POST /api/accounts/refresh` 是唯一账号远端刷新入口；它需要管理员鉴权。
- 图片请求只会选择本地已知可用、额度大于 0、未禁用、未异常且未处于冷却期的账号。`needs_refresh=true` 的账号必须先手动刷新。
- `services/data_management_service.py` 会按设置启动备份线程。默认 `backup_interval_minutes=0`，不自动备份；开启后会把 SQLite 快照、上传图目录和生成图目录打包到 `data/backups/`。
