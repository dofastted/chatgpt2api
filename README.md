# chatgpt2api

本项目仅供学习与研究交流。请务必遵循 OpenAI 的使用条款及当地法律法规，不得用于非法用途！

ChatGPT 图片生成代理与账号池管理面板，提供账号维护、额度刷新和图片生成接口。

## 功能

- 批量导入和管理 `access_token`
- 管理员手动刷新账号邮箱、类型、图片额度、恢复时间
- 轮询可用账号进行图片生成
- 失效 Token 自动剔除
- 提供 Web 后台管理账号和生成图片
- 支持 `user key` 直调图片接口，并按每个 key 自己的模型单价扣减次数
- 当前公开生图模型为 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`
- 支持兑换码；管理员可生成 `20` 或 `100` 额度兑换码，用户 key 兑换后会直接增加额度
- 后台管理页已改成 tab 布局，账号池、用户 key、兑换码分开管理
- 支持本地参考图上传，上传记录按当前 Bearer Token 隔离保存
- 提供独立画廊页 `/gallery`，可搜索图片和 prompt，并把 prompt 带回画图页
- 管理员可在号池管理页维护出站代理；手动刷新账号和生图请求会使用当前启用代理
- 运行数据主存储为 `data/chatgpt2api.sqlite3`；旧 JSON 文件只作为首次导入和人工备份来源
- 管理员页提供“数据管理”，可查看 SQLite 状态、手动备份、本地备份限制、S3 备份上传设置和最近日志
- 生图请求会写入 SQLite 请求记录；管理员可按请求 id、状态、模型和入口查询耗时、扣费和路线摘要

生图界面：
![image](assets/image.png)

号池管理：
![image](assets/account_pool.png)

## 接口

所有接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

可用的 key 有三类：

- `auth-key`：普通使用
- `admin-auth-key`：后台管理
- `user key`：普通调用，但有自己独立的剩余次数和模型单价；当前默认是 `gpt-image-2=2`、`gpt-image-2-2K=2`、`gpt-image-2-4K=8`

前端购买与兑换：

- 画图页顶部保留“兑换中心”入口
- 购买 20 额度兑换码：`https://ldc.fkcodex.com/buy/4`
- 购买 100 额度兑换码：`https://ldc.fkcodex.com/buy/5`
- 兑换码只对 `user key` 开放
- 每次兑换会在当前 `user key` 剩余额度上继续增加，不会重置成固定值

### 图片生成

```http
POST /v1/images/generations
```

请求体示例：

```json
{
  "prompt": "a cyberpunk cat walking in rainy Tokyo street",
  "model": "gpt-image-2",
  "n": 1,
  "response_format": "b64_json"
}
```

说明：

- `model` 当前支持 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`；三个公开模型发往 ChatGPT 上游时都使用 `gpt-image-2`
- `size` 默认 `auto`；传 `WIDTHxHEIGHT` 时会按 16 的倍数向下规整
- `user key` 调用时，实际扣费 = 当前 key 的模型单价 × `n`
- 响应会额外返回 `billing`，包含本次模型、单价、实际扣减次数和剩余次数
- 如果上游页面返回了可复制文本，响应还会额外带 `copied_text`
- 服务现在有三层限制：全局请求队列、当前 Bearer Token 的活动请求上限、账号并发槽位
- 单个账号最多同时跑 2 个生图；10 个健康账号时，最多同时跑 20 个生图
- 单个 Bearer Token 默认最多允许 10 个活动请求，活动数按 `waiting + running` 计算；超过后会返回 `429`
- 全局等待队列默认一直等，但等待数超过 2000 时会返回 `503`
- 可选请求头 `X-Image-Queue-Request-Id` 可让前端或调用方查询自己的排队状态，也会作为请求记录主键；查询接口是 `GET /api/image-queue/me`
- 如果上游返回 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit 或 temporarily unavailable 这类瞬时错误，服务会自动换下一个可用账号重试
- 某个账号命中上游失败后会暂停 3 分钟，再参与下一轮选号
- 支持 `stream: true`。流式时会返回 `image_generation.partial_image`，最后返回 `image_generation.completed` 和 `data: [DONE]`

### Response 生图兼容

```http
POST /v1/responses
```

当前支持范围：

- 主入口是 `POST /v1/responses`
- 走 `tools: [{ "type": "image_generation" }]` 的生图请求
- 如果没有传 `image_generation` tool，会当作第三方客户端健康检查处理，只校验 Bearer Token 并返回 `output_text=ok`、`metadata.health_check=true`，不进上游、不扣费
- 支持文本输入生图，也支持文本加 1 张 `input_image`
- 顶层 `model` 按 OpenAI 官方格式应传文本模型，比如 `gpt-5`、`gpt-5.4`
- `input_image` 支持两种写法：`image_url` 只接受 `http(s)` 或 `data:image/*`，`file_id` 对应本地上传接口返回的文件标识
- 图片模型放在 `tools[].model`，当前支持 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`；如果没传，默认按 `gpt-image-2` 处理，三个公开模型发往 ChatGPT 上游时都使用 `gpt-image-2`
- 图片尺寸放在 `tools[].size`，默认 `auto`；非 `auto` 会规整后传给上游
- 支持 `previous_response_id` 指向本服务生成过的 response，用于带入最近历史文本上下文；记录保存在 SQLite，容器重启后仍可读取；找不到会返回 `404`
- `n` 最多 10
- 返回 `response.output[]`，其中图片结果项是 `type: "image_generation_call"`，图片 base64 在 `result`
- 如果上游页面返回了可复制文本，响应顶层还会带 `copied_text`
- 同样会按 `user key` 自己的模型单价扣费，并在响应里返回 `billing`
- 这条入口也走同一套三层队列；单个账号最多 2 并发，单个 Bearer Token 默认最多 10 个活动请求，全局等待超过 2000 时返回 `503`
- 可选请求头 `X-Image-Queue-Request-Id` 可配合 `GET /api/image-queue/me` 查看当前 Bearer Token 的排队状态
- 如果上游返回 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit 或 temporarily unavailable 这类瞬时错误，服务会自动换下一个可用账号重试
- 某个账号命中上游失败后会暂停 3 分钟，再参与下一轮选号
- 支持 `stream: true`。流式时会依次返回 `response.created`、`response.in_progress`、`response.output_item.added`、`response.image_generation_call.completed`、`response.output_item.done`、`response.completed`，最后返回 `data: [DONE]`；其中 `response.image_generation_call.completed` 会带上本次图片 `result`，便于客户端收到图片后立即结束当前消息
- 单数 `/v1/response` 不是有效接口。

### 图片编辑兼容

```http
POST /v1/images/edits
```

说明：

- 接收 `multipart/form-data`，字段包含 `prompt`、`image`，可选 `model`、`n`、`response_format`、`size` 和 `stream`
- `model` 当前支持 `gpt-image-2`、`gpt-image-2-2K`、`gpt-image-2-4K`；三个公开模型发往 ChatGPT 上游时都使用 `gpt-image-2`
- 当前实现会把上传图片转为输入图，再走同一套队列、账号池、上游请求和用户 key 计费规则

前端图片页现在会先把参考图上传到本地接口，再在 `/v1/responses` 里提交 `input_image.file_id`。本地历史仍保留缩略图预览和 `fileId`，刷新页面后还能区分输入图和生成结果。同一页面里切到别的会话时，正在生成的结果也会继续写回原会话。如果上游页面返回了可复制文本，前端会把这段文本保存到当前会话，并提供复制按钮。前端画图页会把选中的公开模型放在 `tools[].model`，并把当前尺寸选择放在 `tools[].size`。

当前暂不支持：

- 多张输入图

### 兑换码接口

管理员：

- `GET /api/redeem-codes`
- `POST /api/redeem-codes`
- `DELETE /api/redeem-codes`

用户 key：

- `POST /api/redeem-codes/redeem`

说明：

- 管理员现在只能生成 `20` 或 `100` 额度的兑换码
- 兑换成功后，返回 `added_quota` 和最新 `remaining_quota`
- 同一个兑换码只能使用一次

### 本地上传接口

```http
POST /backend-api/files/process_upload_stream
GET /backend-api/my/recent/uploaded_images?limit=25&images_app_only=false
GET /backend-api/files/{file_id}/content
```

说明：

- 上传接口接收 `multipart/form-data`，字段名是 `file`
- 单张图片大小上限是 8 MB
- 支持的输入图片类型有 `png`、`jpeg`、`webp`、`gif`、`bmp`、`avif`
- 上传原图保存在本地 `data/uploaded_images/`，元数据保存在 SQLite；旧 `data/uploaded_images.json` 只用于首次导入
- 上传列表会按当前 Bearer Token 隔离，只返回自己的记录
- 上传成功后会返回 `file_id`、尺寸、大小和下载地址；这个 `file_id` 可以直接放进 `/v1/responses` 的 `input_image`
- 前端图片页选图时默认先走这组接口，不再把大图直接塞进请求体

### 代理管理接口

管理员：

- `GET /api/proxies`
- `POST /api/proxies`
- `DELETE /api/proxies`

说明：

- 代理记录保存在 SQLite；旧 `data/proxies.json` 只用于首次导入，可用 `CHATGPT2API_PROXIES_FILE` 或 `proxies-file` 指向导入来源
- 支持 `http` 和 `socks5`
- 同一时间只有一个代理处于启用状态
- 没有启用代理时，账号刷新和生图请求直连上游

### 上传验收

- 2026-04-23 在本地 `http://127.0.0.1:3002` 上，用 `Authorization: Bearer test-123`
- 先上传 `.llmdoc-tmp/api-image-tests/gpt-image-2.png`
- 再调用 `/v1/responses`，用上传返回的 `file_id` 作为 `input_image`
- 返回 200，结果图保存在 `.llmdoc-tmp/api-image-tests/uploaded-abc123-result.png`
- 实际结果图内容是 `ABC123`

### 云端并发验收

- 2026-04-26 在 `https://img.fkcodex.com` 上执行 20 个真实生图请求：`1K=10`、`2K=6`、`4K=4`
- `/v1/responses` 和 `/v1/images/generations` 各 10 个请求，两个 user key 交替使用
- 20 个请求全部成功，平均耗时 `24.29s`，P95 耗时 `46.89s`
- 扣费结果：`gpt-image-2` 共 10 次扣 20，`gpt-image-2-2K` 共 6 次扣 12，`gpt-image-2-4K` 共 4 次扣 32
- 队列采样显示全局运行峰值 20、全局等待峰值 3、单 key 等待峰值 2，请求结束后 `waiting=0`、`running=0`
- 本次报告保存在 `.llmdoc-tmp/cloud-queue-checks/20260426-173010/report.json`

### 账号刷新兜底

- 账号池请求前会先刷新远端信息
- 如果刷新时只是瞬时网络错误，比如 TLS、连接重置、超时，而本地缓存账号仍可用，则会临时使用缓存状态继续请求
- 如果是 `401` 这类确定失效，则仍按异常账号处理

### 数据管理与备份

管理员接口：

- `GET /api/data-management/status`
- `GET/PUT /api/data-management/settings`
- `POST /api/data-management/backups`
- `GET /api/data-management/backups`
- `POST /api/data-management/s3/test`
- `GET /api/data-management/logs`
- `GET/POST/DELETE /api/image-conversations`
- `GET /api/image-requests`
- `GET /api/image-requests/{request_id}`
- `GET /api/image-queue/admin`

说明：

- SQLite 默认路径是 `data/chatgpt2api.sqlite3`，可用 `CHATGPT2API_SQLITE_PATH` 或 `sqlite-path` 覆盖
- 本地备份默认写到 `data/backups/`，可用 `backup-dir` 覆盖
- `CHATGPT2API_BACKUP_MAX_BYTES` 默认 `524288000`，超过后删除最旧 `.tar.gz` 快照
- `CHATGPT2API_BACKUP_INTERVAL_MINUTES` 默认 `0`，表示不启用定时备份
- 备份包包含 SQLite 快照、`data/uploaded_images/` 和 `data/generated_images/`
- S3 只接收备份包上传，不影响上传图和生成图的本地读取
- 请求记录保存在 `image_request_records`，只保存 prompt 前 80 字、prompt sha256、Bearer Token 哈希、账号哈希、耗时、扣费和错误摘要，不保存完整 prompt、原始请求体或 base64 图片

## 部署

```bash
git clone git@github.com:dofastted/chatgpt2api.git
cp config.example.json config.json
# 编辑 config.json密钥
docker compose up -d
```

## 社区支持
学 AI , 上 L 站

[LinuxDO](https://linux.do)
