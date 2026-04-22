---
mode: plan
task: 图片上传接口接入 chat 与 API
created_at: "2026-04-22T22:39:20+08:00"
complexity: complex
---

# Plan: 图片上传接口接入 chat 与 API

## Goal
- 支持在 chat 页面上传本地图片并参与图片生成或续改。
- 支持 API 侧按 OpenAI 官方风格接收图片输入，而不是只支持纯文本生图。
- 保持现有额度、排队、SSE 结束事件和鉴权行为不回退。

## Scope
- In:
- 为 `POST /v1/response` 和 `POST /v1/responses` 增加图片输入解析。
- 为上游 ChatGPT 会话补齐输入图片附件上传与引用能力。
- 为图片页 chat composer 增加图片选择、预览、删除和发送。
- 为前端会话历史补齐“输入图片”存储字段。
- 为后端和前端补齐测试与验收路径。
- Out:
- 第一版不做独立 `file_id` 对外文件仓库。
- 第一版不改 `/v1/images/generations` 的纯文本生图入口语义。
- 第一版不做多图编辑和复杂工作流编排。
- 第一版不做持久化文件存储服务。

## Assumptions / Dependencies
- 现有主 API 入口仍以 `Responses` 为第一落点，旧 `images/generations` 继续保留。
- 第一版 chat 前端用 data URL 或公网 URL 作为输入图片来源，不新增单独上传后再引用的前端流程。
- 上游会话支持附件方式输入图片；仓库当前尚未实现上传 helper，需要补这条链路。
- 用户 key 的额度结算仍沿用现有预扣、失败退回逻辑。
- 仍以本地 `docker compose -f docker-compose-local.yml up -d --build` 作为主验收部署方式。

## Phases
1. 明确协议边界与输入格式。
   确认 `Responses` 请求中允许的 `input_text`、`input_image`、`image_url`、data URL 范围，明确第一版只支持哪些字段。
2. 调整 API 请求解析层。
   在 `services/api.py` 中扩展 `ResponsesCreateRequest` 和输入提取逻辑，支持文本和图片混合输入，并对不支持的格式给出明确错误。
3. 补齐上游附件上传链路。
   在 `services/image_service.py` 中增加图片准备、上传和消息附件引用逻辑，把当前 `attachments: []` 改成可带输入图片的消息体。
4. 调整图片生成调用封装。
   在服务层明确区分“纯文本生图”和“带图续改”，同时保证 billing、排队和流式完成事件不变。
5. 调整前端 chat 输入区。
   在 `web/src/app/image/page.tsx` 增加上传按钮、缩略图预览、删除已选图和发送时的请求切换。
6. 调整前端数据结构与 API 封装。
   在 `web/src/lib/api.ts` 增加 `Responses` 请求封装，在 `web/src/store/image-conversations.ts` 保存输入图片元数据。
7. 补齐测试与文档。
   新增后端单测覆盖 `input_image` 与流式结束行为，更新 llmdoc 与接口说明。

## Tests & Verification
- `Responses` 请求只带文本时仍能成功生图 -> 现有接口回归测试。
- `Responses` 请求带 1 张输入图片和文本时可成功返回结果 -> 新增进程内 API 测试。
- 不支持的图片输入格式会返回 `400` 且错误信息清楚 -> 新增参数校验测试。
- `stream: true` 时带图请求最后仍返回 `response.completed` 和 `data: [DONE]` -> SSE 测试。
- 带图请求上游失败时，`user_key` 额度会退回 -> 后端计费测试。
- 前端可选择图片、预览、移除，再发起请求 -> 本地手测。
- 刷新页面后，历史记录仍能看到本次输入图片与结果 -> 本地手测。
- `python -m py_compile services/api.py tests/test_user_key_pricing.py tests/test_image_service_attachments.py` 通过。
- `docker compose -f docker-compose-local.yml up -d --build` 通过。

## Issue CSV
- Path: issues/2026-04-22_22-39-20-image-upload-chat-and-api.csv
- Must share the same timestamp and slug as this plan.

## Tools / MCP
- `feedback:codebase_retrieval`，检索 `Responses`、附件上传和前端 chat 现有实现。
- `functions:exec_command`，读取代码、运行测试、构建和部署。
- `functions:apply_patch`，写入后端、前端、测试和文档修改。
- `web:search_query/open`，核对 OpenAI 官方协议文档。

## Acceptance Checklist
- [ ] `POST /v1/response` 和 `POST /v1/responses` 支持 1 张输入图片加文本。
- [ ] 纯文本图片生成路径不回退。
- [ ] 流式响应事件顺序和结束标记不回退。
- [ ] `user_key` 额度在成功、失败两种情况下都正确结算。
- [ ] chat 页面可上传、预览、删除输入图片。
- [ ] chat 页面发送后的历史记录能区分输入图片和输出图片。
- [ ] 本地构建和容器部署通过。
- [ ] llmdoc 和 README 中的接口说明同步更新。

## Risks / Blockers
- 当前仓库没有现成的上游“输入图片上传”实现，最可能卡在这一步。
- 如果 data URL 体积太大，前端直发会让请求体膨胀，需要在第一版限制文件大小和格式。
- 如果上游要求先创建文件资源再引用，第一版范围会扩大，可能需要追加独立上传接口。
- 历史记录目前只存输出图，补输入图后要避免本地存储体积过快膨胀。

## Rollback / Recovery
- 若上游附件上传不稳定，可先保留后端解析和前端上传 UI，但在服务层显式返回“暂不支持带图续改”。
- 若前端历史存储过重，可先只保留当前会话内预览，不落本地持久化。
- 若 `Responses` 带图路径影响现有纯文本流式行为，可先按请求里是否存在图片输入做分流，确保旧路径不受影响。

## Checkpoints
- Commit after: API 解析层和协议校验完成。
- Commit after: 上游附件上传与生成调用完成。
- Commit after: 前端 chat 上传、预览和发送完成。
- Commit after: 测试、文档和部署验证完成。

## References
- `services/api.py`
- `services/image_service.py`
- `services/backend_service.py`
- `web/src/app/image/page.tsx`
- `web/src/lib/api.ts`
- `web/src/store/image-conversations.ts`
- `tests/test_user_key_pricing.py`
- `tests/test_image_service_attachments.py`
- `llmdoc/architecture/backend-api.md`
- `llmdoc/architecture/image-generation-flow.md`
- `llmdoc/reference/http-endpoints.md`
- https://platform.openai.com/docs/guides/tools-image-generation
