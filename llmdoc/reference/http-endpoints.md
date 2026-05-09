# http-endpoints

接口都走 Bearer Token，说明见 `README.md:25`。

公开接口：

- `GET /v1/models`，返回 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`，位置在 `services/api.py`。每个模型条目都带 `endpoint=/v1/responses`、`type=responses`、Responses 能力和对应的默认图片工具。
- `POST /v1/chat/completions`，轻量健康检查兼容入口。它只验证 Bearer Token 并返回一条 `ok` assistant 消息，`metadata.health_check=true`，不走上游聊天、不生图、不扣费。
- `GET /v1/responses` 和 `HEAD /v1/responses`，轻量探活入口，会校验 Bearer Token 并返回当前 key 的队列简况，不进入生图队列。
- `POST /v1/responses`，主 Response 生图入口，位置在 `services/api.py` 的 Responses 路由段。
- `GET /v1/responses/{response_id}`，读取刚创建过的 Response 结果，位置在 `services/api.py` 的 Responses 路由段。
- `GET /version`，返回当前版本，位置在 `services/api.py:293`。

登录与会话：

- `POST /auth/login`，校验 key 后返回 `ok`、`version`、`role`、`auth_type`、`remaining_quota`。如果当前是 `user_key`，还会带 `pricing`、`user_key_id`、`user_key_label`，位置在 `services/api.py:283`。
- `GET /auth/session`，返回当前 key 对应的角色、剩余次数和可选 `pricing`，位置在 `services/api.py:288`。

普通用户可用：

- `GET /api/quota`，普通密钥返回账号池总额度。用户 key 返回自己的剩余次数和 `pricing`，位置在 `services/api.py:399`。
- `POST /api/donations/accounts`，接收 `tokens: string[]` 或 `accounts: object[]`，把账户按“捐赠”分类入池，然后刷新账号信息，位置在 `services/api.py:635`。
- `POST /api/redeem-codes/redeem`，只给 `user_key` 使用。请求体是 `code`。成功后返回这次增加的 `added_quota`、最新 `remaining_quota` 和兑换码条目；这次额度会直接加到当前剩余额度上。
- `GET /api/gallery/public`，读取公开可见画廊项。只返回 `published` 且 `visibility=1` 的项，按置顶、排序和发布时间排列；首次调用时会触发静态 seed 导入。列表响应不会返回旧 base64 图片正文，旧 `data:image/*;base64,...` 资产会以 `/api/gallery/assets/{asset_id}` 形式返回。
- `GET /api/gallery/assets/{asset_id}`，读取旧 `data:image/*;base64,...` 画廊资产的图片内容。该端点用于兼容已有记录，不改变列表响应的轻量形状；非 base64 data URL 和普通 HTTP URL 不会被这个端点解码。
- `POST /api/gallery/{item_id}/events`，记录公开画廊项点击或使用。请求体是 `event: "click" | "use"`。只有公开可见项可记录，非公开项返回 `404`。
- `POST /api/gallery/submissions`，普通用户提交画廊项给管理员审核。请求体包含 `prompt`、可选 `title`、`assets[]`、`source_conversation_id`、`source_turn_id` 和 `source_image_id`。后端保存当前 Bearer Token 的 owner hash，不保存原始 key。
- `POST /backend-api/files/process_upload_stream`，接收 `multipart/form-data` 的 `file` 字段，大小上限 8 MB，返回 `file_id`、`mime_type`、尺寸、大小和下载地址，位置在 `services/api.py:859` 到 `services/api.py:880` 与 `services/uploaded_image_service.py:143` 到 `services/uploaded_image_service.py:184`。
- `GET /backend-api/my/recent/uploaded_images?limit=25&images_app_only=false`，返回当前 Bearer Token 自己最近上传的图片，位置在 `services/api.py:882` 到 `services/api.py:896`。
- `GET /backend-api/files/{file_id}/content`，读取当前 Bearer Token 自己的已上传原图，位置在 `services/api.py:898` 到 `services/api.py:913`。
- `GET /api/image-queue/me`，返回当前 Bearer Token 的队列状态。可选查询参数 `request_id` 会带回那一条请求的 `status`、`position`、`ahead`、`started_at`、`finished_at`、耗时和错误信息。接口同时返回当前 Bearer Token 的等待数、运行数、活动数，全局等待数、运行数、活动数，以及 60 次/60 秒启动限制的窗口状态。查询会清理超时的内存队列 ticket 和 SQLite 活动请求记录；如果请求已经只剩 SQLite 终态记录，仍会在 `request` 字段返回。当前 Bearer Token 是该请求 owner 时，`request` 还会带 `response_id`、`requested_count`、`succeeded_count`、`failed_count`、`charged_quota`、`remaining_quota` 和 `http_status`，用于前端按 `response_id` 读取完成结果。
- `POST /v1/images/generations`，请求体是 `prompt`、`model`、`n`，也兼容 `stream`、`background`、`quality`、`size`、`response_format`、`output_format`、`partial_images`、`output_compression`。`n` 最多 10。`size` 默认为 `auto`；传 `WIDTHxHEIGHT` 时会按 16 的倍数向下规整。`model` 当前接受 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`，三个公开模型发往 ChatGPT 上游时都使用 `gpt-image-2`。`response_format=url` 时会保存生成图并返回 `/v1/images/generated/{image_id}` 的 HTTP URL，用于兼容 Cherry Studio 这类客户端；默认仍返回 `b64_json`。用户 key 只按成功图片数扣费，默认单价是 `1K=2`、`2K=2`、`4K=8`，成功响应里会带 `billing`；部分成功时还会带 `partial_errors`。如果上游页面正文里带了可复制文本，响应顶层还会多一个 `copied_text`。这条接口支持可选请求头 `X-Image-Queue-Request-Id`，并走队列：单个 Bearer Token 默认最多 10 个活动请求、全局等待超过 2000 时返回 `503`、全局最多启动 60 个生图请求/60 秒、账号并发由账号槽位控制。流式时会先给可选的 `image_generation.partial_image`，最后给 `image_generation.completed` 和 `data: [DONE]`；图片事件同时带 SSE `event:` 名和 JSON `type` 字段。
- `GET /v1/responses` 和 `HEAD /v1/responses`，轻量探活入口。它们只验证 Bearer Token，返回 `status=ok`、`auth_type`、空 `data` 和当前 key 的队列简况，不会触发上游生图。
- `POST /v1/responses`，当前支持 `input_text` 加 `tools: [{ "type": "image_generation" }]` 的生图请求，也支持再附带 1 张 `input_image`。没有传 `image_generation` tool 时，这条接口只作为第三方客户端健康检查：校验 Bearer Token 后返回 `output_text=ok` 和 `metadata.health_check=true`，不进入上游、不扣费，也不写生图请求记录。`input_image.image_url` 只接受 `http(s)` 或 `data:image/*`；`input_image.file_id` 对应本地上传接口返回的文件标识。顶层 `model` 可以传文本模型，也可以传 `gpt-image-2`；图片模型放在 `tools[].model`，当前支持 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`，没传时默认 `gpt-image-2`，三个公开模型发往 ChatGPT 上游时都使用 `gpt-image-2`。`tools[].size` 默认为 `auto`；非 `auto` 尺寸会规整后传给上游。请求体还支持 `n`，最多 10。`n > 1` 时服务端会拆成多次内部单图请求再合并结果，聚合层最多同时启动 3 个内部槽位；部分成功时，成功图片留在 `response.output[]`，失败图片写入顶层 `partial_errors`，`user_key` 只按成功张数扣费，默认单价是 `1K=2`、`2K=2`、`4K=8`，`billing` 会带 `requested_count`、`succeeded_count` 和 `failed_count`。`previous_response_id` 可以指向本进程内已有 response，服务会带入最近历史文本上下文；找不到会返回 `404`。结果放在 `response.output[]` 里的 `image_generation_call`，图片 base64 在 `result`。如果上游页面正文里带了可复制文本，响应顶层还会多一个 `copied_text`。如果上游只返回文本不返回图片，响应顶层会带 `text_content`、`copied_text` 和 `output_text`，`response.output[]` 里会有 `message/output_text`，不会按图片成功扣费。这条接口也支持 `X-Image-Queue-Request-Id`，并走队列：单个 Bearer Token 默认最多 10 个活动请求、全局等待超过 2000 时返回 `503`、全局最多启动 60 个生图请求/60 秒、账号并发由账号槽位控制。流式生图会立即返回 `response.created`、`response.in_progress`，等待期间继续发 `response.in_progress` 心跳；有图片时每张成功图都会返回带顶层 `index` 的 `response.image_generation_call.completed` 和 `response.output_item.done`，最后返回 `response.completed` 和 `data: [DONE]`；只有文本时返回 `response.output_item.added`、`response.output_item.done`、`response.completed` 和 `data: [DONE]`；失败时返回 `response.failed` 和 `data: [DONE]`。
- `POST /v1/images/edits`，兼容 multipart 图片编辑。字段包含 `prompt`、`image`，可选 `model`、`n`、`response_format`、`size`、`stream`、`background`、`quality`、`output_format` 和 `partial_images`。当前会把上传图片转成单张输入图，再走同一套队列、账号池和计费规则。
- `GET /v1/responses/{response_id}`，可读回本服务生成过的 Response 结果；记录保存在 SQLite，容器重启后仍可读取。单数路径不注册。
- 当前三个公开图片模型都直接走真实上游 `gpt-image-2`，不再转 `gpt-5.4-thinking`。

管理员可用：

- `GET /api/accounts`，返回账号列表，位置在 `services/api.py:297`。
- `POST /api/accounts`，接收 `tokens: string[]` 或 `accounts: object[]`，先新增再刷新账号信息，默认按“普通”分类入池，位置在 `services/api.py:607`。
- 当传 `accounts` 时，后端会按 token 合并完整账号对象，而不是只提取 `access_token`。
- `DELETE /api/accounts`，接收 `tokens: string[]`，位置在 `services/api.py:377`。
- `POST /api/accounts/refresh`，接收 `access_tokens: string[]`，为空时刷新全部，位置在 `services/api.py:412`。
- `POST /api/accounts/update`，接收 `access_token` 和部分更新字段；更新字段现在可包含 `category`，位置在 `services/api.py:425`。
- `GET /api/user-keys`，返回用户 key 列表，列表项现在带 `pricing`，位置在 `services/api.py:302` 和 `services/user_key_service.py:100`。
- `POST /api/user-keys`，接收 `count`、`quota`、`prefix`、`label_prefix`，也可选传 `pricing`，批量生成用户 key，位置在 `services/api.py:362`。
- `DELETE /api/user-keys`，接收 `keys: string[]`，位置在 `services/api.py:388`。
- `POST /api/user-keys/update`，接收 `key` 和部分更新字段，更新字段可包含 `quota`、`ldc_balance`、`status`、`pricing`，位置在 `services/api.py:453`。前端的批量编辑就是对选中的 key 逐条调用这条接口。
- `GET /api/redeem-codes`，返回兑换码列表。
- `POST /api/redeem-codes`，接收 `count`、`target_quota`、`prefix`、`label`。兼容旧字段名 `targetQuota`。`target_quota` 现在只允许 `20` 或 `100`。
- `DELETE /api/redeem-codes`，接收 `codes: string[]`。前端会用它处理选中兑换码删除，也会拿它一次删掉全部已使用兑换码。
- `GET /api/proxies`，返回代理列表和当前启用代理 URL。
- `POST /api/proxies`，新增或更新代理。字段包含 `id`、`name`、`protocol`、`host`、`port`、`username`、`password`、`enabled`，其中 `protocol` 只支持 `http` 和 `socks5`。
- `DELETE /api/proxies`，请求体是 `id`。删除当前启用代理后，如果还有剩余代理，会启用列表第一项。
- `GET /api/data-management/status`，管理员查看 SQLite 路径、表记录数、备份目录、备份占用和最近备份。
- `GET /api/data-management/settings`，管理员读取数据管理设置；S3 secret 会脱敏返回。
- `PUT /api/data-management/settings`，管理员保存本地备份、会话保存、日志保存和 S3 上传设置。
- `POST /api/data-management/backups`，管理员创建一次本地备份。备份包包含 SQLite 快照、`data/uploaded_images/` 和 `data/generated_images/`。
- `GET /api/data-management/backups`，管理员读取备份记录。
- `POST /api/data-management/s3/test`，管理员测试 S3 配置。测试失败不会保存 secret。
- `GET /api/data-management/logs`，管理员按可选 `limit`、`level`、`component`、`since` 查询最近日志。
- `GET /api/image-requests`，管理员查询生图请求记录。支持 `request_id`、`owner_id`、`auth_type`、`status`、`model`、`endpoint`、`since`、`until`、`limit`、`cursor`。
- `GET /api/image-requests/{request_id}`，管理员读取单条生图请求记录。记录只含摘要、哈希、耗时、扣费、错误和路线字段。
- `GET /api/image-queue/admin`，管理员查看当前所有活动队列 ticket 和全局限制。
- `GET /api/admin/gallery`，管理员读取公开画廊和用户投稿。支持 `status` 和 `limit` 查询参数，响应包含 `items` 和按状态统计的 `status`；列表里的旧 base64 资产同样返回 `/api/gallery/assets/{asset_id}`。
- `PATCH /api/admin/gallery/{item_id}`，管理员更新画廊项。请求体可包含 `action`，支持 `approve`、`reject`、`publish`、`hide`、`delete`、`pin`、`unpin`；也可更新 `prompt`、`title`、`tags`、`sort_order`、`visibility` 和 `assets`。
- `DELETE /api/admin/gallery/{item_id}`，管理员软删除画廊项，实际把状态改成 `deleted` 并隐藏。
- `GET /api/image-conversations`，读取当前 Bearer Token 的图片会话；传 `summary=true` 时只读 `summary_payload` 等轻字段，返回轻量摘要，只含最新 turn、`turnCount` 和状态字段，不带生成图 base64。旧记录没有摘要时会返回可点击的行级占位摘要，单条详情仍走完整 payload。
- `GET /api/image-conversations/{conversation_id}`，读取当前 Bearer Token 下单条图片会话的完整内容。
- `POST /api/image-conversations`，保存或更新当前 Bearer Token 的图片会话；返回的 `items` 使用轻量摘要，避免保存后再传回完整图片列表。
- `DELETE /api/image-conversations`，按 `id` 或 `conversation_id` 删除当前 Bearer Token 的图片会话；返回的 `items` 使用轻量摘要。

前端对应封装：

- 登录、会话、额度、账号列表、新增、捐赠新增、刷新、更新都在 `web/src/lib/api.ts:98` 到 `web/src/lib/api.ts:245`。
- proxy 列表、新增、更新和删除封装在 `web/src/lib/api.ts` 的 `fetchProxies`、`upsertProxy`、`deleteProxy`。
- 公开画廊、用户投稿、公开项统计和管理员画廊管理封装在 `web/src/lib/api.ts` 的 `fetchPublicGalleryItems`、`recordGalleryItemEvent`、`submitGalleryItem`、`fetchAdminGalleryItems`、`updateAdminGalleryItem`、`deleteAdminGalleryItem`。
- 图片页上传和最近上传列表封装在 `web/src/lib/api.ts:350` 到 `web/src/lib/api.ts:364`。
- 数据管理和图片会话接口封装在 `web/src/lib/api.ts`，会话读写由 `web/src/store/image-conversations.ts` 统一调用。
