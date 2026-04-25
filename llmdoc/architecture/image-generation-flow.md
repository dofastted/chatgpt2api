# image-generation-flow

图片生成请求可以从两条入口进入：

- 旧接口 `POST /v1/images/generations`，位置在 `services/api.py:558`。
- 新兼容层主入口是 `POST /v1/responses`，第一版支持文本加单张 `input_image`，位置在 `services/api.py` 的 Responses 路由段。单数 `/v1/response` 不再注册。
- 图片编辑兼容入口是 `POST /v1/images/edits`，接收 multipart 图片并转成单张 `input_image`，再进入同一套队列和账号池路径。

两条路最终都会交给 `BackendService.generate_with_pool`，位置在 `services/backend_service.py:37`。

处理顺序：

- 如果当前鉴权是 `user_key`，会先按这个 key 自己的 `pricing[model] * n` 预扣次数，公共逻辑在 `services/api.py:176`。
- 先从账号池选一个当前可用的 token，逻辑在 `services/backend_service.py:38`。
- 再用 `services/backend_service.py:21` 先刷新这个 token 的远端信息，确认它还有额度、状态也可用。
- 刷新结果不满足条件时会跳过这个 token，继续尝试下一个。
- 选号后会按账号套餐选择执行路线：Free 账号走 Images 路线，Plus/Pro/Team 账号走 Responses 路线，判断点在 `services/chat_image/route_selector.py` 和 `services/backend_service.py`。
- 真正的远端图片请求交给 `services/image_service.py`。

远端请求过程：

- Session 和指纹头在 `services/image_service.py:88` 组装。
- Chat requirements token 在 `services/image_service.py:184` 获取。
- 如果请求里带 `input_image.image_url`，会先抓取或解码图片；如果带 `input_image.file_id`，会先从 `services/uploaded_image_service.py:212` 读取本地已上传文件。
- 本地上传入口是 `services/api.py:859` 到 `services/api.py:913`。前端图片页会先调用 `web/src/lib/api.ts:350` 到 `web/src/lib/api.ts:364` 上传图片，再在 `web/src/app/image/page.tsx:545` 到 `web/src/app/image/page.tsx:558` 把 `fileId` 保存到当前输入图状态。
- 上传到 ChatGPT 上游的过程在 `services/image_service.py`。预上传请求会带 `mime_type`，随后上传 blob，再调用上传确认接口。
- Free/legacy 会话消息有输入图时使用 Studio 同款 `multimodal_text`，`content.parts` 同时包含文本和 `image_asset_pointer`，`metadata.attachments` 只作为附件索引保留。图片指针不能只放在 `metadata.attachments`，否则模型可能识别不到输入图。
- Free 账号的 Images 路线优先请求上游 `/backend-api/f/conversation`，并带 `client_prepare_state=none` 与 `supported_encodings=["v1"]`。
- Plus/Pro/Team 账号的 Responses 路线请求上游 `/backend-api/codex/responses`，顶层文本模型使用 `gpt-5.4-mini`，图片工具模型使用调用方请求的 `gpt-image-2`。
- legacy 回退路线仍请求上游 `/backend-api/conversation`，可通过 `IMAGE_ROUTE_POLICY=legacy` 开启。
- 会话流请求在 `services/image_service.py` 发出。
- SSE 解析在 `services/image_service.py:295`，会从流里提取文件标识和文字结果。
- 当前公开模型只保留 `gpt-image-2`。API 层会在 `services/api.py:217` 拒绝 `gpt-image-1`，默认模型也改成 `gpt-image-2`。
- `gpt-image-2` 直接走真实上游模型 `gpt-image-2`，转换逻辑在 `services/image_service.py` 的 `_resolve_upstream_target`。
- 如果请求来自 `user_key`，成功响应还会附带 `billing`，里面有本次模型、单价、实际扣减次数和剩余次数，公共逻辑在 `services/api.py:206`。
- 如果入口是 `/v1/responses`，结果还会被包成 `response.output[]`，图片项类型是 `image_generation_call`。对外应按官方格式把文本模型放在顶层 `model`，把真实图片模型放在 `tools[].model`；如果没传图片模型，当前默认按 `gpt-image-2` 处理。
- 对外协议转换都在 `services/api.py`。`build_responses_payload` 和 `iter_responses_stream` 负责 Responses 风格输出；`build_images_response_payload` 和 `iter_images_stream` 负责图片接口风格输出。
- 如果上游页面正文里带了可复制文本，`services/image_service.py:1008` 会先收下，再由 `services/api.py:492` 和 `services/api.py:519` 透传成响应顶层字段 `copied_text`。
- `/v1/images/generations` 流式时，图片事件会带 `event: image_generation.completed`，事件内容里也有 `type: image_generation.completed`，最后一定会给 `data: [DONE]`。
- `/v1/responses` 流式时，最后一定会给 `response.completed` 和 `data: [DONE]`。
- 前端图片页现在会把已选参考图的缩略图、`fileId` 和 `copied_text` 一起存进本地会话历史，刷新后仍能区分“参考图”“生成结果”和“可复制文本”，实现见 `web/src/store/image-conversations.ts`。
- 同一页面里切到别的会话时，仍在生成的请求不会被立刻改成“页面已刷新，生成已中断”；真正落盘结果回来后会继续写回原会话，处理点在 `web/src/app/image/page.tsx` 和 `web/src/store/image-conversations.ts`。

2026-04-23 本地实测现状：

- 用本地 `3002` 上的真实接口、`Authorization: Bearer test-123` 和 `.llmdoc-tmp/api-image-tests/gpt-image-2.png` 先调本地上传接口，再用返回的 `file_id` 请求 `/v1/responses`，返回 200。
- 本次结果图保存到 `.llmdoc-tmp/api-image-tests/uploaded-abc123-result.png`，实测内容是 `ABC123`。
- 这说明当前仓库已经支持“本地上传参考图 -> Responses `file_id` 输入图 -> 上游附件生图 -> 本地拿回结果图”的整条路径。

失败处理：

- 请求先进入 `services/image_queue_service.py` 的进程内队列。等待中的请求按全局 FIFO 排；同一个 Bearer Token 最多保留 10 个等待请求；全局等待数超过 2000 时直接拒绝。
- 进入运行阶段后，真正的并发上限由 `services/account_service.py` 的账号槽位控制。单个账号最多同时跑 2 个生图；如果没有空闲槽位，请求会保持在 `assigning_account` 状态继续等。
- 前端会给每次请求附带 `X-Image-Queue-Request-Id`，再通过 `GET /api/image-queue/me` 查询当前 Bearer Token 的等待数、运行数、当前请求位置和状态。
- 成功和失败统计都回写账号池，见 `services/account_service.py:329`。
- 如果报错命中失效 token 条件，判断在 `services/image_service.py:205`，随后 `services/backend_service.py:68` 会把 token 从池里删掉。
- 如果请求前刷新失败，`services/backend_service.py:27` 会把这个账号标成 3 分钟冷却，跳过后继续试下一个。
- 如果上游会话返回瞬时错误，`services/image_service.py` 会把 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit、temporarily unavailable 这类信号都当作可重试失败；`services/backend_service.py` 会跳过当前账号继续试。
- 如果整个池里没有可用 token，`services/backend_service.py:38` 会抛出 `503`。
- 请求完成后，不论是 JSON 还是 SSE，都会在响应真正发完后才从运行态移除。`/v1/images/generations` 和 `/v1/images/edits` 要等 `image_generation.completed` 与 `data: [DONE]` 发完；`/v1/responses` 要等 `response.completed` 与 `data: [DONE]` 发完。
