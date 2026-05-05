# AI SDK Backend Integration Guidelines

## 1. Overview

This document covers backend integration patterns using the Vercel AI SDK (`ai` package) for AI-powered features.

### Supported Providers
- **OpenAI**: GPT-4o, GPT-4o-mini, GPT-4-turbo
- **Google Gemini**: gemini-1.5-pro, gemini-1.5-flash
- **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus

### Package Dependencies
```bash
pnpm add ai @ai-sdk/openai @ai-sdk/google @ai-sdk/anthropic
```

## 2. Basic Usage

### generateText

Use `generateText` for simple text generation tasks where you need a complete response.

```typescript
import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";

const { text } = await generateText({
  model: openai("gpt-4o-mini"),
  prompt: "Summarize this document...",
});
```

### generateObject (Structured Output with Zod)

Use `generateObject` when you need type-safe structured output. The AI SDK validates the response against your Zod schema automatically.

```typescript
import { generateObject } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";

const classificationSchema = z.object({
  category: z.enum(["urgent", "normal", "low"]),
  confidence: z.number().min(0).max(1),
  reasoning: z.string(),
});

const { object } = await generateObject({
  model: openai("gpt-4o-mini"),
  schema: classificationSchema,
  prompt: "Classify the priority of this task...",
});
// object is typed as { category: "urgent" | "normal" | "low", confidence: number, reasoning: string }
```

### streamText (For SSE/Streaming)

Use `streamText` for real-time streaming responses, ideal for chat interfaces and long-form content generation.

```typescript
import { streamText } from "ai";
import { openai } from "@ai-sdk/openai";

const result = streamText({
  model: openai("gpt-4o"),
  messages: conversationHistory,
  system: "You are a helpful assistant.",
});

// Return as SSE stream
return result.toDataStreamResponse();
```

### Image Responses Streaming Contract

#### 1. Scope / Trigger
- Trigger: image generation endpoints stream long-running Responses-compatible events to browsers and API clients.

#### 2. Signatures
- `POST /v1/responses` with `stream: true`
- `GET /api/image-queue/me?request_id=<id>`

#### 3. Contracts
- Success with image: emit `response.created`, repeated `response.in_progress`, image output events, `response.completed`, then `data: [DONE]`.
- Success with text only: emit `response.created`, repeated `response.in_progress`, a `message/output_text` item, `response.completed`, then `data: [DONE]`.
- Failure: emit `response.failed`, then `data: [DONE]`.
- Queue status queries must reconcile both in-memory tickets and stale SQLite active request records.

#### 4. Validation & Error Matrix
- Upstream returns image data -> `response.completed`, request record `finished`, charge successful images.
- Upstream returns text but no image -> `response.completed`, `text_content/output_text`, request record `finished`, charge zero images.
- Upstream throws or times out -> `response.failed`, request record `failed`, queue ticket released.
- Queue record is active in SQLite but missing from memory after timeout -> `GET /api/image-queue/me` returns terminal `request.status=failed`.

#### 5. Good/Base/Bad Cases
- Good: clients can stop waiting on every terminal event, including text-only and failure.
- Base: clients may receive heartbeats before final content.
- Bad: clients must not wait forever for `response.image_generation_call.completed` when final output is text-only.

#### 6. Tests Required
- Unit: payload builder includes `message/output_text` for text-only results.
- Integration: streaming endpoint emits `response.completed` plus `[DONE]` for text-only results.
- Integration: streaming endpoint emits `response.failed` plus `[DONE]` for failures.

#### 7. Wrong vs Correct
- Wrong: treat `data=[]` plus copied text as `ImageGenerationError`.
- Correct: return completed text output and expose it as `text_content`, `copied_text`, and `output_text`.

### Batched Image Generation Contract

#### 1. Scope / Trigger
- Trigger: `/v1/responses`, `/v1/images/generations`, and `/v1/images/edits` accept image generation count `n` greater than `1`.
- This is a cross-layer API contract because backend validation, internal provider calls, SSE events, frontend placeholder slots, and user-key billing must agree on the same indexes and counts.

#### 2. Signatures
- `MAX_IMAGES_PER_REQUEST = 10`
- `IMAGE_BATCH_CONCURRENCY = 3`
- `generate_image_payload(..., n: int, ...) -> (dict[str, object], dict[str, object] | None)`
- `generate_single_image_slot(..., request_index: int, ...) -> ImageBatchSlotResult`
- `generate_image_slots_with_limit(..., requested_count: int, ...) -> list[ImageBatchSlotResult]`

#### 3. Contracts
- Public routes accept `n` in `1..10`; `n > 10` must fail request validation.
- When `n > 1`, the public request is split into `n` internal calls to `BackendService.generate_with_pool(..., n=1, ...)`.
- Internal slot concurrency is capped by `IMAGE_BATCH_CONCURRENCY`, not by public `n`.
- Every successful image item must include original slot `index`.
- Partial failure with at least one success returns success payload plus `partial_errors[]`.
- `partial_errors[]` entries must include `index` and a client-safe `error` string.
- User-key preflight checks `unit_cost * requested_count`; final billing charges `unit_cost * succeeded_count`.
- All failed slots must remain an error response and must not deduct user-key quota.

#### 4. Validation & Error Matrix
- `n=1` -> one internal call, no batch aggregation needed.
- `n=10` -> ten internal calls with at most three active slots.
- `n=11` -> validation error before queue/backend execution.
- Some slots succeed and some fail -> HTTP success with `partial_errors`, success-count billing.
- All slots fail -> error response, zero quota deduction.
- Slot returns text but no image -> preserve text output; do not charge image quota for text-only output.

#### 5. Good/Base/Bad Cases
- Good: output indexes and partial error indexes cover the requested slots without overlap.
- Base: clients may receive successful image events in output order, but event payload still carries original `index`.
- Bad: assuming completion order equals request index; bounded concurrency can change completion order.

#### 6. Tests Required
- Route validation accepts `n=10` and rejects `n=11` for all public image routes.
- Batch aggregation calls `generate_with_pool` with `n=1` for each slot.
- Concurrency test proves active slots never exceed `IMAGE_BATCH_CONCURRENCY`.
- Partial success test proves only successful slots are billed.
- Responses SSE test proves every successful `image_generation_call` emits completed/done events with `index`, then `response.completed` and `[DONE]`.
- Images SSE test proves every successful image emits `image_generation.completed` with `index`, then `[DONE]`.

#### 7. Wrong vs Correct
- Wrong: pass public `n=10` directly into one upstream provider call.
- Correct: split into ten internal `n=1` slot calls and merge results by original slot index.
- Wrong: charge `requested_count` after partial success.
- Correct: preflight against `requested_count`, then deduct only `succeeded_count`.

## 3. Telemetry Configuration

**IMPORTANT**: Always enable telemetry for token tracking and performance monitoring.

```typescript
import { generateObject } from "ai";
import { openai } from "@ai-sdk/openai";

const { object } = await generateObject({
  model: openai("gpt-4o-mini"),
  schema: mySchema,
  prompt,
  experimental_telemetry: {
    isEnabled: true,
    functionId: "orders.classify",  // Module.function naming
    metadata: {
      orderId,
      userId,
    },
  },
});
```

### Telemetry Naming Convention

Use dot-separated format for `functionId`: `module.function`

| Module | Example functionId |
|--------|-------------------|
| Orders | `orders.classify`, `orders.summarize` |
| Support | `support.generateReply`, `support.categorize` |
| Content | `content.summarize`, `content.translate` |
| Users | `users.analyzePreferences` |

### Auto-recorded Metrics

When telemetry is enabled, these metrics are automatically tracked:

| Metric | Description |
|--------|-------------|
| `ai.model.id` | Model identifier (e.g., gpt-4o-mini) |
| `ai.model.provider` | Provider name (e.g., openai) |
| `ai.usage.prompt_tokens` | Input tokens consumed |
| `ai.usage.completion_tokens` | Output tokens generated |
| `ai.usage.total_tokens` | Total tokens used |
| `ai.response.finish_reason` | Completion reason (stop, length, etc.) |

## 4. Tool Calling

Define tools that the AI model can invoke to perform actions in your system.

```typescript
import { generateText, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";

const result = await generateText({
  model: openai("gpt-4o"),
  prompt: "Create a task for the user...",
  tools: {
    createTask: tool({
      description: "Create a new task in the system",
      parameters: z.object({
        title: z.string(),
        dueDate: z.string().optional(),
        priority: z.enum(["high", "medium", "low"]),
      }),
      execute: async ({ title, dueDate, priority }) => {
        const task = await db.insert(tasks).values({
          title,
          dueDate: dueDate ? new Date(dueDate) : null,
          priority,
        }).returning();
        return { success: true, taskId: task[0].id };
      },
    }),
    searchOrders: tool({
      description: "Search for orders by criteria",
      parameters: z.object({
        query: z.string(),
        status: z.enum(["pending", "completed", "cancelled"]).optional(),
        limit: z.number().default(10),
      }),
      execute: async ({ query, status, limit }) => {
        const orders = await db.query.orders.findMany({
          where: and(
            like(orders.title, `%${query}%`),
            status ? eq(orders.status, status) : undefined
          ),
          limit,
        });
        return { orders };
      },
    }),
  },
});

// Access tool results
if (result.toolCalls) {
  for (const toolCall of result.toolCalls) {
    console.log(`Tool: ${toolCall.toolName}`, toolCall.result);
  }
}
```

## 5. Error Handling

Always implement graceful error handling for AI operations.

```typescript
import { generateObject } from "ai";
import { openai } from "@ai-sdk/openai";
import { logger } from "@your-app/logs";

async function classifyOrder(orderData: OrderData) {
  try {
    const { object } = await generateObject({
      model: openai("gpt-4o-mini"),
      schema: classificationSchema,
      prompt: buildClassificationPrompt(orderData),
      experimental_telemetry: {
        isEnabled: true,
        functionId: "orders.classify",
      },
    });
    return { success: true, data: object };
  } catch (error) {
    logger.error("AI generation failed", {
      error,
      orderId: orderData.id,
      prompt: buildClassificationPrompt(orderData).slice(0, 100)
    });

    // Return graceful fallback
    return {
      success: false,
      reason: "AI processing failed",
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}
```

### Common Error Types

| Error | Cause | Resolution |
|-------|-------|------------|
| Rate limit exceeded | Too many requests | Implement exponential backoff |
| Context length exceeded | Prompt too long | Truncate or summarize input |
| Invalid API key | Missing/wrong credentials | Check environment variables |
| Schema validation failed | AI output doesn't match schema | Adjust schema or prompt |

## 6. Prompt Engineering Best Practices

### Use XML Structure for Complex Prompts

XML tags help the AI model better understand the structure of your request.

```typescript
const prompt = `
<context>
${contextData}
</context>

<task>
Analyze the above context and extract key information.
</task>

<output_format>
Return a JSON object with the following fields:
- summary: A brief summary
- keyPoints: Array of key points
- sentiment: positive, negative, or neutral
</output_format>
`;
```

### System Prompts

Define consistent behavior with system prompts.

```typescript
import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";

const result = await generateText({
  model: openai("gpt-4o"),
  system: `You are a professional assistant.
Always respond in a structured format.
Be concise and accurate.
Never make up information - if unsure, say so.`,
  messages: userMessages,
});
```

### Multi-step Prompts

For complex tasks, break down into multiple AI calls.

```typescript
// Step 1: Extract entities
const { object: entities } = await generateObject({
  model: openai("gpt-4o-mini"),
  schema: entitiesSchema,
  prompt: `Extract entities from: ${document}`,
});

// Step 2: Classify based on entities
const { object: classification } = await generateObject({
  model: openai("gpt-4o-mini"),
  schema: classificationSchema,
  prompt: `
<entities>
${JSON.stringify(entities, null, 2)}
</entities>

<task>
Based on these entities, classify the document category.
</task>
`,
});
```

## 7. Provider-Specific Configuration

### OpenAI

```typescript
import { openai } from "@ai-sdk/openai";

const model = openai("gpt-4o-mini", {
  // Optional: custom configuration
});
```

### Google Gemini

```typescript
import { google } from "@ai-sdk/google";

const model = google("gemini-1.5-flash");
```

### Anthropic

```typescript
import { anthropic } from "@ai-sdk/anthropic";

const model = anthropic("claude-3-5-sonnet-20241022");
```

## 8. Best Practices Summary

| Rule | Description |
|------|-------------|
| Always enable telemetry | Track token usage and performance for cost monitoring |
| Use generateObject for structured output | Leverage Zod schemas for type safety and validation |
| Use XML prompts for complex tasks | Better structure improves AI understanding |
| Handle errors gracefully | Return fallback responses, never crash |
| Log AI failures | Include context (truncated prompt, IDs) for debugging |
| Use appropriate model sizes | Use mini models for simple tasks, larger for complex |
| Implement rate limiting | Protect against API quota exhaustion |
| Cache responses when appropriate | Reduce costs for repeated queries |

## 9. Environment Variables

Required environment variables for AI providers:

```bash
# OpenAI
OPENAI_API_KEY=sk-...

# Google Gemini
GOOGLE_GENERATIVE_AI_API_KEY=...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```
