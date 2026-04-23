# chatgpt2api

本项目仅供学习与研究交流。请务必遵循 OpenAI 的使用条款及当地法律法规，不得用于非法用途！

ChatGPT 图片生成代理与账号池管理面板，提供账号维护、额度刷新和图片生成接口。

## 功能

- 批量导入和管理 `access_token`
- 自动刷新账号邮箱、类型、图片额度、恢复时间
- 轮询可用账号进行图片生成
- 失效 Token 自动剔除
- 提供 Web 后台管理账号和生成图片
- 支持 `user key` 直调图片接口，并按每个 key 自己的模型单价扣减次数
- 当前公开生图模型只保留 `gpt-image-2`

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
- `user key`：普通调用，但有自己独立的剩余次数和模型单价；当前默认是 `gpt-image-1=0`、`gpt-image-2=2`

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

- `model` 当前只支持 `gpt-image-2`
- `user key` 调用时，实际扣费 = 当前 key 的模型单价 × `n`
- 响应会额外返回 `billing`，包含本次模型、单价、实际扣减次数和剩余次数
- 如果上游页面返回了可复制文本，响应还会额外带 `copied_text`
- 同一个 key 在 10 秒间隔内的新请求会进入等待队列，不会立刻返回 429；等待队列超过 100 个时才会拒绝
- 如果上游返回 `524`、网关超时或 Cloudflare 类错误，服务会自动换下一个可用账号重试
- 某个账号命中上游失败后会暂停 3 分钟，再参与下一轮选号
- 支持 `stream: true`。流式时会返回 `image_generation.partial_image`，最后返回 `image_generation.completed` 和 `data: [DONE]`

### Response 生图兼容

```http
POST /v1/response
```

当前支持范围：

- 主入口是 `POST /v1/response`，同时兼容 `POST /v1/responses`
- 走 `tools: [{ "type": "image_generation" }]` 的生图请求
- 支持文本输入生图，也支持文本加 1 张 `input_image`
- 顶层 `model` 按 OpenAI 官方格式应传文本模型，比如 `gpt-5`、`gpt-5.4`
- `input_image.image_url` 只支持 `http(s)` 或 `data:image/*`
- 图片模型放在 `tools[].model`，当前只支持 `gpt-image-2`；如果没传，默认按 `gpt-image-2` 处理
- `n` 最多 2
- 返回 `response.output[]`，其中图片结果项是 `type: "image_generation_call"`，图片 base64 在 `result`
- 如果上游页面返回了可复制文本，响应顶层还会带 `copied_text`
- 同样会按 `user key` 自己的模型单价扣费，并在响应里返回 `billing`
- 同一个 key 在 10 秒间隔内的新请求会进入等待队列，不会立刻返回 429；等待队列超过 100 个时才会拒绝
- 如果上游返回 `524`、网关超时或 Cloudflare 类错误，服务会自动换下一个可用账号重试
- 某个账号命中上游失败后会暂停 3 分钟，再参与下一轮选号
- 支持 `stream: true`。流式时会依次返回 `response.created`、`response.in_progress`、`response.output_item.added`、`response.image_generation_call.completed`、`response.output_item.done`、`response.completed`，最后返回 `data: [DONE]`

前端图片页现在也支持上传 1 张参考图。上传后会在聊天输入框里显示缩略图，发送后本地历史会保留这张参考图，刷新页面后仍能区分输入图和生成结果。如果上游页面返回了可复制文本，前端会把这段文本保存到当前会话，并提供复制按钮。

当前暂不支持：

- `previous_response_id`
- 多张输入图

## 部署

```bash
git clone git@github.com:basketikun/chatgpt2api.git
cp config.example.json config.json
# 编辑 config.json密钥
docker compose up -d
```

## 社区支持
学 AI , 上 L 站

[LinuxDO](https://linux.do)
