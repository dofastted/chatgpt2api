# API Integration

This document covers API integration patterns including oRPC client usage, real-time communication, and AI streaming.

## oRPC Client Usage

### Client Setup

```typescript
// lib/orpc.ts
import { createORPCClient } from '@your-app/api/client'; // Replace with your monorepo package path

export const orpcClient = createORPCClient({
  baseUrl: process.env.NEXT_PUBLIC_API_URL,
});
```

### Basic API Calls

```typescript
// Simple GET
const users = await orpcClient.users.list();

// GET with parameters
const user = await orpcClient.users.get({ id: userId });

// POST (create)
const newUser = await orpcClient.users.create({
  name: 'John Doe',
  email: 'john@example.com',
});

// PUT/PATCH (update)
const updatedUser = await orpcClient.users.update({
  id: userId,
  name: 'Jane Doe',
});

// DELETE
await orpcClient.users.delete({ id: userId });
```

### With React Query

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { orpcClient } from '@/lib/orpc';

// Query
export function useUsers() {
  return useQuery({
    queryKey: ['users'],
    queryFn: () => orpcClient.users.list(),
  });
}

// Mutation
export function useCreateUser() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: orpcClient.users.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });
}
```

## Query Patterns

### Image Gallery Asset URL Contract

#### 1. Scope / Trigger

- Trigger: frontend code renders images from `GET /api/gallery/public` or `GET /api/admin/gallery`.
- Use this contract for `/image` gallery rail, `/gallery`, and admin gallery preview/review UI.

#### 2. Signatures

- `fetchPublicGalleryItems({ limit, redirectOnUnauthorized }) -> { items: GalleryItem[] }`
- `fetchAdminGalleryItems({ status, limit }) -> { items: GalleryItem[] }`
- `resolveApiAssetUrl(url: string) -> string`
- `GalleryAsset.url` may be:
  - absolute HTTP(S) URL
  - data URL from local browser-only state
  - relative API URL such as `/api/gallery/assets/{asset_id}`

#### 3. Contracts

- Backend gallery list responses must not contain old `data:image/*;base64,...` bodies for persisted server records.
- When `GalleryAsset.url` starts with `/api/`, frontend rendering code must pass it through `resolveApiAssetUrl()` before assigning it to image `src`.
- `resolveApiAssetUrl()` prefixes relative API URLs with the configured API base. This is required because static export and Next dev may serve the UI from a different origin than the FastAPI backend.
- Do not call `resolveApiAssetUrl()` for local browser-only data URLs or absolute URLs; it must return them unchanged.

#### 4. Validation & Error Matrix

- `/api/gallery/assets/{asset_id}` returns image bytes -> browser displays the old asset.
- `/api/gallery/assets/{asset_id}` returns `404` -> image card should follow existing broken-image/fallback behavior.
- `url` is absolute HTTP(S) -> use as-is.
- `url` is `data:image/...` from local pinned browser state -> use as-is.
- `url` is empty -> skip or reject the gallery item according to existing builder behavior.

#### 5. Good/Base/Bad Cases

- Good: public gallery item with `/api/gallery/assets/asset-1` renders correctly on both static FastAPI origin and Next dev origin.
- Base: user-local pinned image uses a data URL and remains local-only.
- Bad: frontend assigns `/api/gallery/assets/asset-1` directly while running from a different dev origin.
- Bad: frontend assumes gallery list always returns base64 image bodies.

#### 6. Tests Required

- Type check after changing `GalleryAsset` consumers.
- Unit or focused test for URL resolver if test harness exists.
- Browser/API verification that public gallery list response does not include `data:image` and rendered images still load.

#### 7. Wrong vs Correct

##### Wrong

```typescript
return {
  imageUrl: asset.url,
};
```

##### Correct

```typescript
return {
  imageUrl: resolveApiAssetUrl(asset.url),
};
```

### Pagination

```typescript
interface PaginationParams {
  page: number;
  pageSize: number;
}

export function usePaginatedOrders({ page, pageSize }: PaginationParams) {
  return useQuery({
    queryKey: ['orders', { page, pageSize }],
    queryFn: () => orpcClient.orders.list({ page, pageSize }),
    placeholderData: (prev) => prev, // Keep previous data while fetching
  });
}
```

### Filtering and Sorting

```typescript
interface OrderFilters {
  status?: string;
  customerId?: string;
  sortBy?: 'createdAt' | 'total';
  sortOrder?: 'asc' | 'desc';
}

export function useFilteredOrders(filters: OrderFilters) {
  return useQuery({
    queryKey: ['orders', filters],
    queryFn: () => orpcClient.orders.list(filters),
  });
}
```

### Prefetching

```typescript
export function useOrdersWithPrefetch() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['orders', { page: 1 }],
    queryFn: () => orpcClient.orders.list({ page: 1 }),
  });

  // Prefetch next page
  useEffect(() => {
    if (query.data?.hasNextPage) {
      queryClient.prefetchQuery({
        queryKey: ['orders', { page: 2 }],
        queryFn: () => orpcClient.orders.list({ page: 2 }),
      });
    }
  }, [query.data, queryClient]);

  return query;
}
```

## Real-time Communication

### WebSocket with Ably

```typescript
// lib/ably.ts
import Ably from 'ably';

export const ablyClient = new Ably.Realtime({
  authUrl: '/api/ably/auth',
});

// Hook for real-time updates
export function useRealtimeOrders() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const channel = ablyClient.channels.get('orders');

    channel.subscribe('order:created', (message) => {
      queryClient.invalidateQueries({ queryKey: ['orders'] });
    });

    channel.subscribe('order:updated', (message) => {
      const order = message.data;
      queryClient.setQueryData(['orders', order.id], order);
    });

    return () => {
      channel.unsubscribe();
    };
  }, [queryClient]);
}
```

### WebSocket Connection Management

```typescript
export function useWebSocket(channelName: string) {
  const [isConnected, setIsConnected] = useState(false);
  const channelRef = useRef<Ably.RealtimeChannel | null>(null);

  useEffect(() => {
    const channel = ablyClient.channels.get(channelName);
    channelRef.current = channel;

    channel.on('attached', () => setIsConnected(true));
    channel.on('detached', () => setIsConnected(false));

    return () => {
      channel.detach();
    };
  }, [channelName]);

  const subscribe = useCallback(
    (event: string, callback: (data: unknown) => void) => {
      channelRef.current?.subscribe(event, (message) => {
        callback(message.data);
      });
    },
    []
  );

  return { isConnected, subscribe };
}
```

## SSE/Streaming for AI Chat

### Image Responses Stream Handling Contract

#### 1. Scope / Trigger
- Trigger: the image Web UI calls `/v1/responses` with `stream: true` and must never leave a turn spinning after a terminal server event.

#### 2. Signatures
- `generateImage(prompt, model, n, { queueRequestId, clientConversationId, previousResponseId, size })`
- SSE events: `response.completed`, `response.failed`, `response.output_item.done`, `response.image_generation_call.completed`

#### 3. Contracts
- `response.completed.response.output[]` may contain `image_generation_call` items, `message/output_text` items, or both.
- `text_content`, `copied_text`, and `output_text` are valid final payload fields even when no image is returned.
- A `response.failed` event is terminal and must unblock the composer after showing the error.
- `[DONE]` must be consumed as the stream terminator, but the UI should use the preceding terminal event for success or failure data.

#### 4. Validation & Error Matrix
- `response.image_generation_call.completed` with `result` -> save image result and keep waiting for `response.completed`.
- `response.completed` with images -> mark turn success when all requested images succeeded, or error when only part succeeded.
- `response.completed` with `text_content/copy_text` and no images -> mark turn success, show text card, mark image placeholders error.
- `response.failed` -> mark turn error and mark loading images error.
- Queue poll returns `failed/rejected` for a pending turn -> mark that turn error and unblock the composer.

#### 5. Good/Base/Bad Cases
- Good: image, text-only, and failure streams all end with visible user feedback.
- Base: heartbeats may arrive for a long time before final data.
- Bad: deriving success only from image events leaves text-only results stuck in loading state.

#### 6. Tests Required
- Type check for stream parsing shapes.
- Backend integration tests for text-only and failure streams.
- Frontend build after changing stream handling.

#### 7. Wrong vs Correct
- Wrong: throw `生成响应没有结束信号` when no image event was seen but `response.completed` had text output.
- Correct: normalize the completed response, persist `text_content/copied_text`, and stop the active turn.

### Basic SSE Pattern

```typescript
export function useAIChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const sendMessage = useCallback(async (content: string) => {
    setIsStreaming(true);

    // Add user message
    setMessages((prev) => [
      ...prev,
      { role: 'user', content },
    ]);

    // Create placeholder for assistant response
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '' },
    ]);

    try {
      const response = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        setMessages((prev) => {
          const updated = [...prev];
          const lastMessage = updated[updated.length - 1];
          lastMessage.content += chunk;
          return updated;
        });
      }
    } finally {
      setIsStreaming(false);
    }
  }, []);

  return { messages, sendMessage, isStreaming };
}
```

### Using Vercel AI SDK

```typescript
import { useChat } from 'ai/react';

export function useAIChatWithSDK() {
  const {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    isLoading,
    error,
  } = useChat({
    api: '/api/ai/chat',
    onFinish: (message) => {
      // Handle completed message
    },
  });

  return {
    messages,
    input,
    handleInputChange,
    handleSubmit,
    isLoading,
    error,
  };
}
```

## AI Tool Calls Handling

AI responses may include tool calls (function calls). The format differs between real-time streaming and history restore.

### Real-time Streaming Format

During streaming, tool calls arrive incrementally:

```typescript
interface StreamingToolCall {
  type: 'tool-call';
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
}

interface StreamingToolResult {
  type: 'tool-result';
  toolCallId: string;
  result: unknown;
}
```

### History Restore Format

When loading chat history, tool calls are embedded in messages:

```typescript
interface HistoryMessage {
  role: 'assistant';
  content: string;
  toolInvocations?: Array<{
    toolCallId: string;
    toolName: string;
    args: Record<string, unknown>;
    result?: unknown;
    state: 'pending' | 'result' | 'error';
  }>;
}
```

### Unified Handler Pattern

```typescript
interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  state: 'pending' | 'result' | 'error';
}

function normalizeToolCall(
  data: StreamingToolCall | HistoryMessage['toolInvocations'][0]
): ToolCall {
  // Handle streaming format
  if ('type' in data && data.type === 'tool-call') {
    return {
      id: data.toolCallId,
      name: data.toolName,
      args: data.args,
      state: 'pending',
    };
  }

  // Handle history format
  return {
    id: data.toolCallId,
    name: data.toolName,
    args: data.args,
    result: data.result,
    state: data.state,
  };
}

// Usage in component
function ToolCallDisplay({ toolCall }: { toolCall: ToolCall }) {
  switch (toolCall.name) {
    case 'searchProducts':
      return <ProductSearchResult args={toolCall.args} result={toolCall.result} />;
    case 'createOrder':
      return <OrderCreationResult args={toolCall.args} result={toolCall.result} />;
    default:
      return <GenericToolResult toolCall={toolCall} />;
  }
}
```

### Handling Tool Call States

```typescript
export function useToolCallHandler() {
  const [pendingToolCalls, setPendingToolCalls] = useState<Map<string, ToolCall>>(
    new Map()
  );

  const handleStreamChunk = useCallback((chunk: unknown) => {
    if (isToolCall(chunk)) {
      setPendingToolCalls((prev) => {
        const next = new Map(prev);
        next.set(chunk.toolCallId, normalizeToolCall(chunk));
        return next;
      });
    }

    if (isToolResult(chunk)) {
      setPendingToolCalls((prev) => {
        const next = new Map(prev);
        const existing = next.get(chunk.toolCallId);
        if (existing) {
          next.set(chunk.toolCallId, {
            ...existing,
            result: chunk.result,
            state: 'result',
          });
        }
        return next;
      });
    }
  }, []);

  return { pendingToolCalls, handleStreamChunk };
}
```

## Error Handling

### API Error Handling

```typescript
import { isORPCError } from '@your-app/api/client'; // Replace with your monorepo package path

export function useCreateOrder() {
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: orpcClient.orders.create,
    onError: (err) => {
      if (isORPCError(err)) {
        switch (err.code) {
          case 'UNAUTHORIZED':
            setError('Please sign in to continue');
            break;
          case 'VALIDATION_ERROR':
            setError('Please check your input');
            break;
          default:
            setError('Something went wrong');
        }
      } else {
        setError('Network error. Please try again.');
      }
    },
  });

  return { ...mutation, error };
}
```

### Retry Logic

```typescript
export function useResilientQuery() {
  return useQuery({
    queryKey: ['data'],
    queryFn: () => orpcClient.data.get(),
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}
```

## Best Practices

1. **Centralize API Client**: Keep oRPC client configuration in one place
2. **Use Query Keys Consistently**: Follow a hierarchical naming convention
3. **Handle Loading States**: Always show feedback during API calls
4. **Implement Error Boundaries**: Catch and display errors gracefully
5. **Optimize Real-time**: Unsubscribe from channels when components unmount
6. **Type Everything**: Leverage TypeScript for API response types
