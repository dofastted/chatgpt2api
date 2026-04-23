# http-endpoints

接口都走 Bearer Token，说明见 `README.md:25`。

公开接口：

- `GET /v1/models`，返回支持的模型列表，位置在 `services/api.py:273`。
- `POST /v1/response`，主 Response 生图入口；`POST /v1/responses` 保留兼容，位置在 `services/api.py` 的 Responses 路由段。
- `GET /v1/response/{response_id}`，读取刚创建过的 Response 结果；`GET /v1/responses/{response_id}` 保留兼容，位置在 `services/api.py` 的 Responses 路由段。
- `GET /version`，返回当前版本，位置在 `services/api.py:293`。

登录与会话：

- `POST /auth/login`，校验 key 后返回 `ok`、`version`、`role`、`auth_type`、`remaining_quota`。如果当前是 `user_key`，还会带 `pricing`、`user_key_id`、`user_key_label`，位置在 `services/api.py:283`。
- `GET /auth/session`，返回当前 key 对应的角色、剩余次数和可选 `pricing`，位置在 `services/api.py:288`。

普通用户可用：

- `GET /api/quota`，普通密钥返回账号池总额度。用户 key 返回自己的剩余次数和 `pricing`，位置在 `services/api.py:399`。
- `POST /api/donations/accounts`，接收 `tokens: string[]` 或 `accounts: object[]`，把账户按“捐赠”分类入池，然后刷新账号信息，位置在 `services/api.py:635`。
- `POST /backend-api/files/process_upload_stream`，接收 `multipart/form-data` 的 `file` 字段，大小上限 8 MB，返回 `file_id`、`mime_type`、尺寸、大小和下载地址，位置在 `services/api.py:859` 到 `services/api.py:880` 与 `services/uploaded_image_service.py:143` 到 `services/uploaded_image_service.py:184`。
- `GET /backend-api/my/recent/uploaded_images?limit=25&images_app_only=false`，返回当前 Bearer Token 自己最近上传的图片，位置在 `services/api.py:882` 到 `services/api.py:896`。
- `GET /backend-api/files/{file_id}/content`，读取当前 Bearer Token 自己的已上传原图，位置在 `services/api.py:898` 到 `services/api.py:913`。
- `POST /v1/images/generations`，请求体是 `prompt`、`model`、`n`，也兼容 `stream`、`background`、`quality`、`size`、`output_format`、`partial_images`、`output_compression`。`model` 当前只接受 `gpt-image-2`。用户 key 会先按自己 `pricing[model] * n` 预扣，成功保留，失败退回；成功响应里还会带 `billing`。如果上游页面正文里带了可复制文本，响应顶层还会多一个 `copied_text`。同一个 key 在 10 秒间隔内的新请求会进入等待队列，等待数超过 100 才返回 429。若上游返回 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit 或 temporarily unavailable 这类瞬时错误，服务会自动换下一个可用账号重试；当前账号会暂停 3 分钟后再参与下一轮选号。流式时会先给可选的 `image_generation.partial_image`，最后给 `image_generation.completed` 和 `data: [DONE]`。
- `POST /v1/response`，当前支持 `input_text` 加 `tools: [{ "type": "image_generation" }]` 的生图请求，也支持再附带 1 张 `input_image`。`input_image.image_url` 只接受 `http(s)` 或 `data:image/*`；`input_image.file_id` 对应本地上传接口返回的文件标识。顶层 `model` 按官方格式应传文本模型，图片模型放在 `tools[].model`，当前只支持 `gpt-image-2`；如果没传图片模型，默认 `gpt-image-2`。请求体还支持 `n`，最多 2。结果放在 `response.output[]` 里的 `image_generation_call`，图片 base64 在 `result`。如果上游页面正文里带了可复制文本，响应顶层还会多一个 `copied_text`。同一个 key 在 10 秒间隔内的新请求会进入等待队列，等待数超过 100 才返回 429。若上游返回 `408/422/429/500/502/503/504/520/522/524`、网关超时、Cloudflare、rate limit 或 temporarily unavailable 这类瞬时错误，服务会自动换下一个可用账号重试；当前账号会暂停 3 分钟后再参与下一轮选号。流式时会返回 `response.created`、`response.in_progress`、`response.output_item.added`、`response.image_generation_call.completed`、`response.output_item.done`、`response.completed`，最后给 `data: [DONE]`。
- `GET /v1/response/{response_id}`，可读回本进程内刚生成过的 Response 结果；当前不做持久化。复数路径保留兼容。
- 当前 `gpt-image-2` 直接走真实上游 `gpt-image-2`，不再转 `gpt-5.4-thinking`。

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
- `POST /api/user-keys/update`，接收 `key` 和部分更新字段，更新字段可包含 `pricing`，位置在 `services/api.py:453`。

前端对应封装：

- 登录、会话、额度、账号列表、新增、捐赠新增、刷新、更新都在 `web/src/lib/api.ts:98` 到 `web/src/lib/api.ts:245`。
- 图片页上传和最近上传列表封装在 `web/src/lib/api.ts:350` 到 `web/src/lib/api.ts:364`。
