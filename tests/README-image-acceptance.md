# 图片生成链路逐步验收

后端单测：

```bash
python -m pytest tests -q
```

前端检查：

```bash
cd web
npm run lint
npm run build
```

半集成验收脚本改成逐步执行。每一步都会打印关键参数，并把结果写到固定目录。建议先定一个 `run_id`，后面所有步骤都复用它。

示例：

```bash
RUN_ID=img-accept-001
BASE_URL=http://127.0.0.1:18201
AUTH_KEY="$(tr -d '\r\n' < .llmdoc-tmp/image-acceptance/worktree-test-key.txt)"
```

隔离 worktree 推荐用原仓库复制出的 `data-migration/` 运行，不要把该目录提交：

```bash
CHATGPT2API_AUTH_KEY=worktree-auth \
CHATGPT2API_ADMIN_AUTH_KEY=worktree-admin \
CHATGPT2API_DATA_DIR="$PWD/data-migration" \
IMAGE_ENGINE=chat_image \
IMAGE_ROUTE_POLICY=plan_type \
python -m uvicorn main:app --host 127.0.0.1 --port 18201
```

新的图生图标准：

- 第 1 步先生成一张 `ABC` 视图板
- 第 2 步把第 1 步生成出来的结果图重新上传
- 上传时复用第 1 步拿到的 `conversation_id`，确保图片识别和 prompt 在同一会话上下文里
- 第 3 步再基于这张已生成的 `ABC` 视图继续生成“红色 + 黑色版本”
- 最终判断标准不是 OCR，而是看：
  - 是否走了同一会话
  - 是否拿到了新的结果图
  - 结果图是否仍然是 `ABC` 视图变体，而不是完全跑题

第 1 步，生成 ABC 视图：

```bash
python scripts/image_acceptance_runner.py \
  --step text_generate \
  --base-url "$BASE_URL" \
  --auth-key "$AUTH_KEY" \
  --run-id "$RUN_ID"
```

脚本会打印这些关键参数：

- `result_path`
- `request_id`
- `http_status`
- `conversation_id`
- `output_count`
- `queue_last_status`
- `ocr_detail`
- `ok`

这一步默认 prompt 已改成“生成一个清晰的 ABC 三视图展示板”。脚本会生成 `client_conversation_id` 并放进 `/v1/responses` 的 `metadata`，因此不依赖服务端额外返回 `conversation_id`。

第 2 步，上传第 1 步生成结果：

```bash
python scripts/image_acceptance_runner.py \
  --step upload_generated_text_result \
  --base-url "$BASE_URL" \
  --auth-key "$AUTH_KEY" \
  --run-id "$RUN_ID"
```

这一步会打印：

- `result_path`
- `http_status`
- `file_id`
- `client_conversation_id`
- `width`
- `height`
- `size_bytes`
- `ok`

默认会自动读取第 1 步产出的 `result.png` 和 `client_conversation_id`。如果你要换图，也可以手动传 `--input-image` 和 `--client-conversation-id`。

第 3 步，在同一会话里继续图生图：

```bash
python scripts/image_acceptance_runner.py \
  --step image_generate \
  --base-url "$BASE_URL" \
  --auth-key "$AUTH_KEY" \
  --run-id "$RUN_ID"
```

默认会自动读取第 2 步产出的 `file_id` 和 `client_conversation_id`。这一步默认 prompt 已改成“保持同一构图和主体，只把主色改成红色和黑色”。

也可以手动传：

```bash
python scripts/image_acceptance_runner.py \
  --step image_generate \
  --base-url "$BASE_URL" \
  --auth-key "$AUTH_KEY" \
  --run-id "$RUN_ID" \
  --file-id upload_xxx \
  --client-conversation-id conv_xxx
```

这一步会打印：

- `result_path`
- `request_id`
- `file_id`
- `client_conversation_id`
- `http_status`
- `conversation_id`
- `output_count`
- `queue_last_status`
- `ocr_detail`
- `width`
- `height`
- `ok`

第 4 步，汇总读取结果：

```bash
python scripts/image_acceptance_runner.py \
  --step summarize \
  --run-id "$RUN_ID"
```

汇总会打印每一步的关键结果，适合你自己读，也适合交给子 agent 只读产物汇报。

输出目录结构：

- 请求体
- 原始响应
- 队列快照
- 结果图
- 每一步各自的 `result.json`
- 最终 `summary.json`

默认目录：

```text
.llmdoc-tmp/image-acceptance/<run_id>/
```

其中：

- `01_text_generate/`
- `02_upload_generated_text_result/`
- `03_image_generate/`

每个目录里都至少有：

- `response.json`
- `result.json`

有请求和队列的步骤还会带：

- `request.json`
- `queue.json`

OCR 说明：

- 如果本机有 `tesseract`，脚本会尝试做 OCR。
- 如果没有，报告里会写 `未执行 OCR`，不会静默跳过。
