# image-generation-flow

图片生成请求可以从三条公开入口进入：

- `POST /v1/responses` 是公开生图入口，支持文本加单张 `input_image`，位置在 `services/api.py` 的 Responses 路由段。单数 `/v1/response` 不再注册。
- `POST /v1/images/generations` 是第三方客户端兼容入口，接收 JSON，再进入同一个 `generate_image_payload`。
- `POST /v1/images/edits` 是第三方客户端兼容入口，接收 multipart 图片，把 `image` 转成单张 `input_image` 后进入同一个 `generate_image_payload`。
- 三条公开入口都接受图片尺寸。`auto` 是默认值，不传给上游；`WIDTHxHEIGHT` 会先按 16 的倍数向下规整，再进入后端路径。
- `POST /v1/chat/completions` 只作为 API key 健康检查兼容入口，不进入图片生成链路。
- `POST /v1/responses` 如果没有 `image_generation` tool，也只作为第三方客户端健康检查入口，返回 `output_text=ok` 和 `metadata.health_check=true`，不进入图片生成链路。

三条公开生图入口最终都会交给 `BackendService.generate_with_pool`，位置在 `services/backend_service.py:37`。

处理顺序：

- 如果当前鉴权是 `user_key`，会先检查这个 key 的 `pricing[model] * n` 是否足够；只有拿到图片结果后才扣费，公共逻辑在 `services/api.py` 的 `generate_image_payload`。
- 当 `n > 1` 时，服务端会把它拆成 `n` 次内部生成调用，每次传给 `BackendService.generate_with_pool` 的 `n` 都是 `1`。单次公开请求最多 10 张，聚合层最多同时启动 3 个内部槽位；这样单张图命中 `524` 之类的上游错误时，不会丢掉已经成功的其他图片。
- 批量请求如果至少一张成功，会返回成功图片，并在响应顶层带 `partial_errors` 记录失败图片的 `index` 和错误信息；每个成功图片项也带原始 `index`，方便前端放回对应位置。`user_key` 只按成功张数扣费，`billing` 会带 `requested_count`、`succeeded_count` 和 `failed_count`。
- 批量请求如果全部失败，会保持失败响应，不扣 `user_key` 额度。
- 先从账号池选一个当前可用的 token，逻辑在 `services/backend_service.py:38`。
- 再用 `services/backend_service.py:21` 先刷新这个 token 的远端信息，确认它还有额度、状态也可用。
- 刷新结果不满足条件时会跳过这个 token，继续尝试下一个。
- 选号后会按是否带输入图选择内部执行路线：无输入图默认走 `images`，Free 有输入图走 `images_edit`，Plus/Pro/Team 有输入图走 `responses`，判断点在 `services/chat_image/route_selector.py` 和 `services/backend_service.py`。
- 带输入图请求会优先选择最近在 input image responses 路线成功过的账号。账号侧记录 `input_image_success`、`input_image_fail`、`last_input_image_used_at` 和 `last_input_image_success_at`，选择逻辑在 `services/account_service.py`，调用点在 `services/backend_service.py`。
- 如果临时用 `IMAGE_ROUTE_POLICY=force_responses` 让无输入图走 Responses，遇到 `429`、网关超时或其他瞬时上游错误时，同一个账号会先退到 Images 路线再试一次；仍失败才换下一个账号。带输入图的付费账号请求不会退到 `images_edit`。
- 这条分层来自 `IMAGE_ROUTE_POLICY=plan_type` 的默认配置；主容器默认走 `IMAGE_ENGINE=chat_image`，不要退回旧后端协议作为长期方案。
- 真正的远端图片请求交给 `services/image_service.py`。

远端请求过程：

- Session 和指纹头在 `services/image_service.py:88` 组装。
- Chat requirements token 在 `services/image_service.py:184` 获取。
- 如果请求里带 `input_image.image_url`，会先抓取或解码图片；如果带 `input_image.file_id`，会先从 `services/uploaded_image_service.py:212` 读取本地已上传文件。
- 输入图发往上游前会做轻量规整：超过 `1536` 长边或超过 `4 MB` 时，`services/image_service.py` 会尝试用 Pillow 缩放并重新编码；如果处理失败或结果没有变小，就保留原图。
- 本地上传入口是 `services/api.py:859` 到 `services/api.py:913`。前端图片页会先调用 `web/src/lib/api.ts:350` 到 `web/src/lib/api.ts:364` 上传图片，再在 `web/src/app/image/page.tsx:545` 到 `web/src/app/image/page.tsx:558` 把 `fileId` 保存到当前输入图状态。
- 上传到 ChatGPT 上游的过程在 `services/image_service.py`。预上传请求会带 `mime_type`，随后上传 blob，再调用上传确认接口。
- Free/legacy 会话消息有输入图时使用 Studio 同款 `multimodal_text`，`content.parts` 同时包含文本和 `image_asset_pointer`，`metadata.attachments` 只作为附件索引保留。图片指针不能只放在 `metadata.attachments`，否则模型可能识别不到输入图。
- `images` 和 `images_edit` 内部路线优先请求上游 `/backend-api/f/conversation`，并带 `client_prepare_state=none` 与 `supported_encodings=["v1"]`。
- Plus/Pro/Team 带输入图的 Responses 路线请求上游 `/backend-api/codex/responses`，顶层文本模型使用 `gpt-5.4-mini`，图片工具模型使用 `gpt-image-2`。
- 非 `auto` 尺寸会继续传给上游。Images 路线在 conversation 请求中带 `image_generation_options.size`；Responses 路线在 `image_generation` tool 中带 `size`。
- legacy 回退路线仍请求上游 `/backend-api/conversation`，可通过 `IMAGE_ROUTE_POLICY=legacy` 开启。
- 会话流请求在 `services/image_service.py` 发出。
- SSE 解析在 `services/image_service.py:295`，会从流里提取文件标识和文字结果。
- 当前公开模型是 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`。API 层会在 `services/api.py` 的 `normalize_requested_image_model` 拒绝 `gpt-image-1`。
- `/v1/models` 暴露三个公开模型；每个模型条目都会标出 `endpoint=/v1/responses`、`type=responses`、Responses 能力和对应的 `default_image_tool.model`。
- 三个公开模型发往 ChatGPT 上游时都使用真实模型 `gpt-image-2`，转换逻辑在 `services/image_service.py` 的 `_resolve_upstream_target` 和 `_normalize_responses_image_tool_model`。
- 如果请求来自 `user_key`，成功响应还会附带 `billing`，里面有本次模型、单价、实际扣减次数和剩余次数，公共逻辑在 `services/api.py:206`。
- 如果入口是 `/v1/responses`，结果还会被包成 `response.output[]`，图片项类型是 `image_generation_call`。对外应按官方格式把文本模型放在顶层 `model`，把公开图片模型放在 `tools[].model`；如果没传图片模型，当前默认按 `gpt-image-2` 处理。
- `/v1/responses` 顶层 `model` 可以直接传 `gpt-image-2`。这种请求对外 Response 的 `model` 保留 `gpt-image-2`，内部图片模型也按 `gpt-image-2` 执行。
- `/v1/images/generations` 和 `/v1/images/edits` 默认返回 `b64_json`；当第三方客户端传 `response_format=url` 时，会把图片保存到 `data/generated_images/`，并返回 `/v1/images/generated/{image_id}` 的 HTTP URL。这个图片读取 URL 不要求再次带 Authorization，避免 Cherry Studio 二次 fetch 图片时失败。
- `/v1/responses` 现在允许 `previous_response_id` 指向本服务生成过的 response。服务会从 SQLite response 记录读取最近历史，把历史 prompt、尺寸和可复制文本合进本次文本上下文；上游会话标识不足时，响应 `metadata.context_mode` 标成 `text_history`。
- 对外协议转换都在 `services/api.py`。`build_responses_payload` 和 `iter_responses_stream` 负责 Responses 风格输出；`build_images_response_payload` 和 `iter_images_stream` 负责图片接口风格输出。
- 如果上游页面正文里带了可复制文本，`services/image_service.py` 会先收下，再由 `services/api.py` 透传成响应顶层字段 `copied_text`。
- 如果上游只返回文本而没有图片，`services/api.py` 会保留空 `data`，同时返回 `text_content` 和 `copied_text`。`/v1/responses` 会把这段文本放进 `response.output[]` 的 `message/output_text`，并按完成响应结束；`user_key` 只按成功图片数扣费，所以这种文本替代结果不扣图片额度。
- 无输入图 prompt 只有在明确要求生成文字、字母、字体或排版时，`services/image_service.py` 才会追加文字渲染约束，并在下载后执行文字质量复查。普通人像、摄影、写实 prompt，以及明确写了 `no text`、`no watermark`、`无文字` 这类否定词的 prompt，不进入 `low quality text render` 重试链。
- `/v1/images/generations` 和 `/v1/images/edits` 流式时，图片事件会带 `event: image_generation.completed`，事件内容里也有 `type: image_generation.completed`，最后一定会给 `data: [DONE]`。
- `/v1/responses` 流式时，服务端会先返回 `response.created` 和 `response.in_progress`，然后在队列等待和上游生成期间继续发送 `response.in_progress` 心跳，避免 Cloudflare 长时间空等后返回 `524`。最终如果有图片，每张成功图都会有一条 `response.image_generation_call.completed`，事件顶层带原始 `index`、图片 `result` 和完整 `item`；如果只有文本，最终 Response 会带 `message/output_text`。两种成功结果最后都给 `response.completed` 和 `data: [DONE]`。
- 前端收到对应完成事件和 `[DONE]` 后，才能把会话状态从生成中改为完成。只收到图片内容但没有结束事件时，应继续视为协议错误。收到 `response.failed` 时要把本地 turn 和 loading 图片改成错误态。
- 前端图片页调用 `/v1/responses` 时默认传 `stream: true`，会把选中的公开模型放到 `tools[].model`，把当前尺寸选择放到 `tools[].size`，再从 SSE 的 `response.completed` 事件读取最终 Response。它还会累积 `response.image_generation_call.completed` 和 `response.output_item.done` 中的图片项，再合进最终 Response，避免批量生成时逐张图片事件已到、但最终 `output` 不完整导致 Web 占位图一直等待。配置保持自动时，prompt 中明确出现的 `1K`、`2K`、`4K`、`1024`、`2048`、`4096` 或常见高分辨率词只用于页面显示和模型档位推断，不会把 `tools[].size` 从 `auto` 改成固定宽高。它既读取图片项，也读取 `text_content/copied_text`；没有图片但有文本时会结束生成并展示“可复制文本”。公开的 `/v1/images/generations` 和 `/v1/images/edits` 只作为外部兼容入口，项目自带网页不使用。
- 前端图片页现在会把 session 存成多轮 `turns[]`，主存储是后端 `/api/image-conversations`，本地 `localforage` 只做缓存和旧数据上传来源。每轮保存 prompt、模型、张数、尺寸、参考图、结果图、队列 id、`responseId` 和 `copied_text`；旧单轮记录读取时会映射成一个 turn，实现见 `web/src/store/image-conversations.ts`。
- 同一页面里切到别的会话时，仍在生成的请求不会被立刻改成“页面已刷新，生成已中断”；真正落盘结果回来后会继续写回原会话，处理点在 `web/src/app/image/page.tsx` 和 `web/src/store/image-conversations.ts`。
- 在同一 session 继续发送新 prompt 时，前端复用 `clientConversationId`，并把上一轮 `responseId` 作为 `previous_response_id` 发给 `/v1/responses`。

2026-04-23 本地实测现状：

- 用本地 `3002` 上的真实接口、`Authorization: Bearer test-123` 和 `.llmdoc-tmp/api-image-tests/gpt-image-2.png` 先调本地上传接口，再用返回的 `file_id` 请求 `/v1/responses`，返回 200。
- 本次结果图保存到 `.llmdoc-tmp/api-image-tests/uploaded-abc123-result.png`，实测内容是 `ABC123`。
- 这说明当前仓库已经支持“本地上传参考图 -> Responses `file_id` 输入图 -> 上游附件生图 -> 本地拿回结果图”的整条路径。

失败处理：

- 三条生图入口在鉴权和参数校验后会创建 `image_request_records` 记录，主键来自 `X-Image-Queue-Request-Id`，未传时由服务端生成。`/v1/responses` 健康检查不写请求记录。
- 请求记录由 `services/image_request_log_service.py` 写入 SQLite。它只保存 prompt 前 80 字、prompt sha256、Bearer Token 哈希、账号哈希、耗时、扣费、错误和路线摘要，不保存完整 prompt、原始请求体或 base64 图片。
- 请求先进入 `services/image_queue_service.py` 的进程内队列。等待中的请求按全局 FIFO 排；同一个 Bearer Token 默认最多保留 10 个活动请求，活动数按 `waiting + running` 计算；全局等待数超过 2000 时直接拒绝。
- 队列启动运行前还有全局 60 次/60 秒限制。超过这个速率的生图请求继续停在等待态，直到滑动窗口释放名额；健康检查、登录、额度和上传接口不计入。
- 进入运行阶段后，真正的并发上限由 `services/account_service.py` 的账号槽位控制。单个账号最多同时跑 2 个生图；如果没有空闲槽位，请求会保持在 `assigning_account` 状态继续等。
- 前端会给每次请求附带 `X-Image-Queue-Request-Id`，再通过 `GET /api/image-queue/me` 查询当前 Bearer Token 的等待数、运行数、活动数、当前请求位置和状态。查询时服务端同时清理超时的内存队列 ticket 和 SQLite 里的活动请求记录；如果内存队列已经丢失，但 SQLite 记录已进入 `failed/rejected/finished`，接口仍会返回这条 `request`。
- `wait_for_turn` 通过后，请求记录进入 `assigning_account`；`BackendService.generate_with_pool` 选到账户并开始上游调用时进入 `running`，同时记录账号哈希、账号类型、内部路线和尝试次数。
- JSON 请求成功返回前写 `finished`；SSE 请求在最终事件和 `data: [DONE]` 发完后写 `finished`。异常路径写 `failed`，队列或活动数超限写 `rejected`。
- 成功和失败统计都回写账号池，见 `services/account_service.py:329`。
- 如果报错命中失效 token 条件，判断在 `services/image_service.py:205`，随后 `services/backend_service.py:68` 会把 token 从池里删掉。
- 如果请求前刷新失败，`services/backend_service.py:27` 会把这个账号标成 3 分钟冷却，跳过后继续试下一个。
- 如果上游会话返回瞬时错误，`services/image_service.py` 会把 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit、temporarily unavailable 这类信号都当作可重试失败；`services/backend_service.py` 会跳过当前账号继续试。
- 如果整个池里没有可用 token，`services/backend_service.py:38` 会抛出 `503`。
- 请求完成后，不论是 JSON 还是 SSE，都会在响应真正发完后才从运行态移除。`/v1/images/generations` 和 `/v1/images/edits` 流式请求要等 `image_generation.completed` 与 `data: [DONE]` 发完；`/v1/responses` 流式请求要等 `response.completed` 与 `data: [DONE]` 发完。

2026-04-26 云端并发验收：

- `https://img.fkcodex.com` 上混合执行 20 个真实生图请求，其中 `/v1/responses` 10 个、`/v1/images/generations` 10 个。
- 模型分布是 `gpt-image-2` 10 个、`gpt-image-2-2K` 6 个、`gpt-image-2-4K` 4 个。
- 20 个请求全部成功；平均耗时 `24.29s`，P95 耗时 `46.89s`。
- 队列采样显示全局运行峰值 20、全局等待峰值 3、单 key 等待峰值 2，最后 `global.waiting=0`、`global.running=0`。
- 扣费结果是 `1K=20/10次`、`2K=12/6次`、`4K=32/4次`，没有单价不匹配。
- 原始报告在 `.llmdoc-tmp/cloud-queue-checks/20260426-173010/report.json`。
