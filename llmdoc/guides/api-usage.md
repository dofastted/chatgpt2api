# api-usage

这份指南面向外部调用方和本地联调，说明如何用 HTTP API 使用 `chatgpt2api`，以及如何通过管理员接口管理账号池。

## 1. 基础地址与启动前提

本地容器默认地址：

```text
http://127.0.0.1:3002
```

不走容器直接运行 `python main.py` 时，默认监听：

```text
http://127.0.0.1:8000
```

启动前需要在仓库根目录准备 `config.json`。可参考 `config.example.json`，至少配置：

```json
{
  "auth-key": "replace-with-your-auth-key",
  "admin-auth-key": "replace-with-your-admin-auth-key"
}
```

推荐启动方式仍是：

```powershell
docker compose -f docker-compose-local.yml up -d --build
```

如果 Docker 拉取基础镜像受网络影响，也可以先用仓库现有 Python 环境直接启动后端验证：

```powershell
python main.py
```

## 2. 鉴权与角色

所有业务接口都使用 Bearer Token：

```http
Authorization: Bearer <key>
```

可用 key 分三类：

- `auth-key`：普通用户能力，可生图、查额度、上传本地输入图、提交画廊投稿、捐赠上传账号。
- `admin-auth-key`：管理员能力，包含账号池、用户 key、兑换码、代理、数据管理、请求记录和外部账号管理。
- `user key`：管理员生成的独立用户 key，可生图、查自己的剩余额度和模型单价、兑换兑换码。

注意：如果没有单独配置 `admin-auth-key`，服务会回退到 `auth-key`，此时普通用户和管理员没有实际区分。

## 3. 快速健康检查

检查版本：

```powershell
curl http://127.0.0.1:3002/version
```

验证 key 并查看角色：

```powershell
curl -X POST http://127.0.0.1:3002/auth/login `
  -H "Content-Type: application/json" `
  -d '{"key":"replace-with-your-auth-key"}'
```

用 Bearer Token 查看当前会话：

```powershell
curl http://127.0.0.1:3002/auth/session `
  -H "Authorization: Bearer replace-with-your-auth-key"
```

查看可用模型：

```powershell
curl http://127.0.0.1:3002/v1/models `
  -H "Authorization: Bearer replace-with-your-auth-key"
```

当前公开图片模型：

- `gpt-image-2`
- `gpt-image-2-2K`
- `gpt-image-2-4K`

## 4. 图片生成接口

### OpenAI Images 风格

```http
POST /v1/images/generations
```

示例：

```powershell
curl -X POST http://127.0.0.1:3002/v1/images/generations `
  -H "Authorization: Bearer replace-with-your-auth-key" `
  -H "Content-Type: application/json" `
  -d '{
    "prompt": "a cyberpunk cat walking in rainy Tokyo street",
    "model": "gpt-image-2",
    "n": 1,
    "size": "auto",
    "response_format": "b64_json"
  }'
```

常用字段：

- `prompt`：必填，图片提示词。
- `model`：可选，默认 `gpt-image-2`。
- `n`：可选，最多 10。
- `size`：可选，默认 `auto`；传 `WIDTHxHEIGHT` 时会按 16 的倍数向下规整。
- `response_format`：可选，默认 `b64_json`；传 `url` 时返回 `/v1/images/generated/{image_id}` HTTP 地址，若配置了 `CHATGPT2API_PUBLIC_BASE_URL`，会优先拼到这个公开基址下。
- `stream`：可选，`true` 时返回 SSE。

### OpenAI Responses 风格

```http
POST /v1/responses
```

示例：

```powershell
curl -X POST http://127.0.0.1:3002/v1/responses `
  -H "Authorization: Bearer replace-with-your-auth-key" `
  -H "Content-Type: application/json" `
  -d '{
    "model": "gpt-5",
    "input": "draw a small robot holding a red umbrella",
    "tools": [
      {"type": "image_generation", "model": "gpt-image-2", "size": "auto"}
    ],
    "n": 1
  }'
```

约定：

- 顶层 `model` 可按第三方客户端习惯传文本模型。
- 图片模型放在 `tools[].model`。
- 没有 `image_generation` tool 时，这个接口只作为健康检查返回 `ok`，不进上游、不扣费。
- 结果在 `response.output[]`，图片项类型是 `image_generation_call`，base64 在 `result`。
- `previous_response_id` 可以指向本服务保存过的 response，用于带入最近历史文本上下文。

## 5. 本地参考图上传

上传单张输入图：

```powershell
curl -X POST http://127.0.0.1:3002/backend-api/files/process_upload_stream `
  -H "Authorization: Bearer replace-with-your-auth-key" `
  -F "file=@C:\path\to\input.png"
```

上传成功后会返回 `file_id`，可放进 `/v1/responses` 的 `input_image.file_id`：

```json
{
  "model": "gpt-5",
  "input": [
    {
      "role": "user",
      "content": [
        {"type": "input_text", "text": "turn this into watercolor style"},
        {"type": "input_image", "file_id": "file_xxx"}
      ]
    }
  ],
  "tools": [{"type": "image_generation", "model": "gpt-image-2"}]
}
```

上传记录按当前 Bearer Token 隔离。单张文件大小上限是 8 MB。

## 6. 队列与请求进度

图片接口支持请求头：

```http
X-Image-Queue-Request-Id: custom-request-id
```

查询当前 key 的队列和某个请求状态：

```powershell
curl "http://127.0.0.1:3002/api/image-queue/me?request_id=custom-request-id" `
  -H "Authorization: Bearer replace-with-your-auth-key"
```

队列规则摘要：

- 单个 Bearer Token 默认最多 10 个活动请求。
- 全局等待数超过 2000 时返回 `503`。
- 全局默认最多启动 60 个生图请求/60 秒。
- 账号并发由账号槽位控制。

## 7. 账号池与外部账号管理

### 关键结论：仍然需要 AT/access_token

账号导入的核心凭据仍是 `access_token`，也就是常说的 AT。`session`、`oai-device-id`、`oai-session-id`、`user-agent`、`refresh_token`、`id_token` 等字段只作为兼容外部系统和上游指纹的附加信息保存，不能替代 `access_token`。

导入纯 token 或只带 auth 产物的账号后，账号会标记为 `needs_refresh=true`。这类账号在管理员手动刷新成功前不参与图片选号。

### 管理员新增普通账号

```http
POST /api/accounts
```

纯 token：

```powershell
curl -X POST http://127.0.0.1:3002/api/accounts `
  -H "Authorization: Bearer replace-with-your-admin-auth-key" `
  -H "Content-Type: application/json" `
  -d '{"tokens":["access-token-1","access-token-2"]}'
```

完整账号对象：

```json
{
  "accounts": [
    {
      "access_token": "access-token-1",
      "email": "user@example.com",
      "refresh_token": "refresh-token-1",
      "oai-device-id": "device-id-1",
      "oai-session-id": "session-id-1",
      "user-agent": "Mozilla/5.0 ..."
    }
  ],
  "category": "普通"
}
```

### 外部系统上传账号

```http
POST /api/external/accounts
```

这个接口只允许管理员 key 调用，适合外部系统直接推送自己的账号 JSON。请求体支持三种承载方式：

- `tokens: string[]`
- `accounts: object[]`
- `payload` 或 `accountJson`：任意嵌套 JSON，后端会递归提取可用账号

示例：

```powershell
curl -X POST http://127.0.0.1:3002/api/external/accounts `
  -H "Authorization: Bearer replace-with-your-admin-auth-key" `
  -H "Content-Type: application/json" `
  -d '{
    "payload": {
      "data": {
        "accounts": [
          {
            "auth": {
              "authorization": "Bearer access-token-1",
              "refreshToken": "refresh-token-1"
            },
            "session": {
              "oaiDeviceId": "device-id-1",
              "oaiSessionId": "session-id-1",
              "userAgent": "Mozilla/5.0 ..."
            },
            "metadata": {
              "email": "user@example.com"
            }
          }
        ]
      }
    },
    "category": "普通"
  }'
```

后端会识别这些 token 字段名：

- `access_token`
- `access-token`
- `accessToken`
- `chatgpt_access_token`
- `chatgpt-access-token`
- `chatgptAccessToken`
- `token` 或 `authorization`，但只有看起来像 access token 时才会作为 fallback 使用

会保留的常见外部字段：

- `refresh_token` / `refreshToken`
- `id_token` / `idToken`
- `email`
- `account_id` / `accountId`
- `user_id` / `userId`
- `proxy_key` / `proxyKey`
- `user-agent` / `userAgent`
- `oai-device-id` / `oaiDeviceId`
- `oai-session-id` / `oaiSessionId`
- `sec-ch-ua`、`sec-ch-ua-mobile`、`sec-ch-ua-platform`

### 捐赠上传账号

```http
POST /api/donations/accounts
```

这个接口普通 key 和用户 key 也能调用，账号会按“捐赠”分类入池。请求体同样支持 `tokens`、`accounts`、`payload`、`accountJson`。

### 刷新与管理账号

新增账号不会自动访问上游刷新信息。管理员需要手动刷新：

```powershell
curl -X POST http://127.0.0.1:3002/api/accounts/refresh `
  -H "Authorization: Bearer replace-with-your-admin-auth-key" `
  -H "Content-Type: application/json" `
  -d '{"access_tokens":["access-token-1"]}'
```

传空数组会刷新全部账号：

```json
{"access_tokens":[]}
```

常用管理接口：

- `GET /api/accounts`：查看账号列表。
- `DELETE /api/accounts`：按 token 删除账号。
- `POST /api/accounts/update`：更新单个账号的 `category`、`status`、`quota` 等字段。

## 8. 用户 key 与兑换码

管理员生成用户 key：

```powershell
curl -X POST http://127.0.0.1:3002/api/user-keys `
  -H "Authorization: Bearer replace-with-your-admin-auth-key" `
  -H "Content-Type: application/json" `
  -d '{"count":1,"quota":20,"prefix":"uk","label_prefix":"user"}'
```

用户 key 查询额度：

```powershell
curl http://127.0.0.1:3002/api/quota `
  -H "Authorization: Bearer <user-key>"
```

用户 key 兑换兑换码：

```powershell
curl -X POST http://127.0.0.1:3002/api/redeem-codes/redeem `
  -H "Authorization: Bearer <user-key>" `
  -H "Content-Type: application/json" `
  -d '{"code":"redeem-code"}'
```

默认模型单价：

- `gpt-image-2 = 2`
- `gpt-image-2-2K = 2`
- `gpt-image-2-4K = 8`

用户 key 只按成功图片数扣费。部分成功时，响应会带 `partial_errors`，`billing` 会说明请求数、成功数、失败数和实际扣费。

## 9. 常见错误

- `401 authorization is invalid`：Bearer Token 缺失或错误。
- `403 admin authorization is required`：当前 key 不是管理员 key。
- `403 user key authorization is required`：兑换码接口必须用用户 key。
- `400 account JSON contains no usable access_token`：外部账号 JSON 没有可用 AT；session 字段不能替代 AT。
- `429`：当前 Bearer Token 活动请求过多，或账号/队列限制命中。
- `503`：全局等待队列过大或服务暂不可接收新请求。
- 上游或本机代理报 `curl: (7) Failed to connect ... 10808`：先检查本机 Clash/代理连通性，再短退避重试；不要先判断成账号坏或文字质量审查问题。

## 10. 相关文档

- `llmdoc/guides/local-run.md`：本地启动和部署边界。
- `llmdoc/reference/http-endpoints.md`：完整接口清单。
- `llmdoc/architecture/backend-api.md`：后端路由和协议转换。
- `llmdoc/architecture/account-pool-and-refresh.md`：账号池、导入、刷新和可用性规则。
