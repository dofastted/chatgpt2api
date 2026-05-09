import webConfig from "@/constants/common-env";
import { httpRequest, httpStreamRequest } from "@/lib/request";

export type AccountType = "Free" | "Plus" | "Pro" | "Team";
export type AccountStatus = "正常" | "限流" | "异常" | "禁用";
export type AccountCategory = "普通" | "捐赠";
export type ImageModel = "gpt-image-2" | "gpt-image-2-2K" | "gpt-image-2-4K";
export type AuthRole = "user" | "admin";
export type AuthType = "auth_key" | "admin_auth_key" | "user_key";
export type ProxyProtocol = "http" | "socks5";
export type UserKeyStatus = "启用" | "停用";
export type UserKeyPricing = {
  "gpt-image-2": number;
  "gpt-image-2-2K": number;
  "gpt-image-2-4K": number;
};

export type ImageBilling = {
  requested_model: ImageModel;
  unit_cost: number;
  charged_quota: number;
  remaining_quota: number;
};

export type ImageQueueItemStatus =
  | "waiting"
  | "assigning_account"
  | "running"
  | "finished"
  | "failed"
  | "rejected";
export type ImageRequestStatus =
  | "accepted"
  | "waiting"
  | "assigning_account"
  | "running"
  | "finished"
  | "failed"
  | "rejected";

export type ImageQueueItem = {
  request_id: string;
  title?: string | null;
  status: ImageQueueItemStatus;
  position?: number | null;
  ahead?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  response_id?: string | null;
  requested_count?: number | null;
  succeeded_count?: number | null;
  failed_count?: number | null;
  charged_quota?: number | null;
  remaining_quota?: number | null;
  http_status?: number | null;
  queue_wait_ms?: number | null;
  running_ms?: number | null;
  total_ms?: number | null;
};

export type Account = {
  id: string;
  access_token: string;
  category: AccountCategory;
  type: AccountType;
  status: AccountStatus;
  quota: number;
  email?: string | null;
  user_id?: string | null;
  limits_progress?: Array<{
    feature_name?: string;
    remaining?: number;
    reset_after?: string;
  }>;
  default_model_slug?: string | null;
  restoreAt?: string | null;
  success: number;
  fail: number;
  lastUsedAt: string | null;
  needsRefresh?: boolean;
};

export type ProxyItem = {
  id: string;
  name: string;
  protocol: ProxyProtocol;
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  enabled: boolean;
  url?: string | null;
};

export type ImportedAccount = {
  access_token: string;
  [key: string]: unknown;
};

export type UserKey = {
  id: string;
  key: string;
  label?: string | null;
  quota: number;
  ldcBalance: number;
  status: UserKeyStatus;
  pricing: UserKeyPricing;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastUsedAt?: string | null;
};

export type RedeemCodeStatus = "未使用" | "已使用";

export type RedeemCode = {
  id: string;
  code: string;
  label?: string | null;
  targetQuota: number;
  status: RedeemCodeStatus;
  createdAt?: string | null;
  updatedAt?: string | null;
  usedAt?: string | null;
  usedByKey?: string | null;
};

export type DataManagementSettings = {
  backup_enabled: boolean;
  backup_interval_minutes: number;
  backup_max_bytes: number;
  save_image_conversations: boolean;
  save_logs: boolean;
  s3: {
    enabled: boolean;
    endpoint: string;
    region: string;
    bucket: string;
    access_key_id: string;
    secret_access_key: string;
    prefix: string;
    force_path_style: boolean;
    use_ssl: boolean;
  };
};

export type DataBackupRecord = {
  id: string;
  path: string;
  size_bytes: number;
  status: string;
  error?: string | null;
  s3_uploaded: boolean;
  s3_error?: string | null;
  created_at: string;
};

export type DataManagementLogItem = {
  id: number;
  created_at: string;
  level: string;
  component: string;
  message: string;
  context?: Record<string, unknown>;
};

export type DataManagementStatus = {
  sqlite_path: string;
  exists: boolean;
  size_bytes: number;
  tables: Record<string, number>;
  backup_dir: string;
  backup_size_bytes: number;
  backup_max_bytes: number;
  backup_count: number;
  latest_backup?: DataBackupRecord | null;
  settings: DataManagementSettings;
};

export type GalleryItemStatus =
  | "pending"
  | "published"
  | "rejected"
  | "hidden"
  | "deleted";

export type GalleryItemSource = "seed" | "user_submission" | "admin";

export type GalleryAsset = {
  asset_id: string;
  kind: string;
  url: string;
  file_id?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  size_bytes?: number | null;
  created_at?: string | null;
};

export function resolveApiAssetUrl(url: string): string {
  const normalizedUrl = String(url || "").trim();
  if (!normalizedUrl.startsWith("/api/")) {
    return normalizedUrl;
  }
  const apiUrl = webConfig.apiUrl.replace(/\/$/, "");
  return apiUrl ? `${apiUrl}${normalizedUrl}` : normalizedUrl;
}

export type GalleryItem = {
  id: string;
  status: GalleryItemStatus;
  visibility: boolean;
  source: GalleryItemSource;
  prompt: string;
  prompt_preview: string;
  title?: string | null;
  tags: string[];
  assets: GalleryAsset[];
  cover_asset_id?: string | null;
  sort_order: number;
  is_pinned: boolean;
  submitted_by_owner_id?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  created_at: string;
  updated_at: string;
  published_at?: string | null;
  last_clicked_at?: string | null;
  last_used_at?: string | null;
  click_count: number;
  use_count: number;
  metadata?: Record<string, unknown>;
};

export type GallerySubmissionPayload = {
  prompt: string;
  title?: string;
  tags?: string[];
  assets?: Array<{
    url: string;
    kind?: string;
    mime_type?: string;
    width?: number;
    height?: number;
    size_bytes?: number;
  }>;
  image_url?: string;
  mime_type?: string;
  source_conversation_id?: string;
  source_turn_id?: string;
  source_image_id?: string;
};

export type AdminGalleryUpdatePayload = {
  action?: "approve" | "reject" | "hide" | "publish";
  status?: GalleryItemStatus;
  visibility?: boolean;
  prompt?: string;
  title?: string;
  tags?: string[];
  assets?: GallerySubmissionPayload["assets"];
  image_url?: string;
  mime_type?: string;
  sort_order?: number;
  is_pinned?: boolean;
};

type AccountListResponse = {
  items: Account[];
};

type UserKeyListResponse = {
  items: UserKey[];
};

type RedeemCodeListResponse = {
  items: RedeemCode[];
};

type ProxyListResponse = {
  items: ProxyItem[];
  active_proxy_url?: string | null;
};

type GalleryListResponse = {
  items: GalleryItem[];
  status?: Record<string, number>;
};

type GalleryMutationResponse = {
  item: GalleryItem;
  items?: GalleryItem[];
  status?: Record<string, number>;
  removed?: number;
};

type AccountMutationResponse = {
  items: Account[];
  added?: number;
  updated?: number;
  skipped?: number;
  removed?: number;
  refreshed?: number;
  rewarded_accounts?: number;
  rewarded_quota?: number;
  rewarded_ldc?: number;
  remaining_quota?: number | null;
  ldc_balance?: number | null;
  errors?: Array<{ access_token: string; error: string }>;
};

type UserKeyMutationResponse = {
  items: UserKey[];
  created_items?: UserKey[];
  added?: number;
  removed?: number;
};

type RedeemCodeMutationResponse = {
  items: RedeemCode[];
  created_items?: RedeemCode[];
  item?: RedeemCode;
  added?: number;
  removed?: number;
  remaining_quota?: number | null;
  ldc_balance?: number | null;
  purchased_quota?: number;
  spent_ldc?: number;
  previous_quota?: number;
  added_quota?: number;
};

type AccountRefreshResponse = {
  items: Account[];
  refreshed: number;
  errors: Array<{ access_token: string; error: string }>;
};

type AccountUpdateResponse = {
  item: Account;
  items: Account[];
};

type ProxyUpsertResponse = {
  item: ProxyItem;
  items: ProxyItem[];
  active_proxy_url?: string | null;
};

type UserKeyUpdateResponse = {
  item: UserKey;
  items: UserKey[];
};

type AuthSessionResponse = {
  ok: boolean;
  version: string;
  role: AuthRole;
  auth_type?: AuthType;
  remaining_quota?: number | null;
  ldc_balance?: number | null;
  pricing?: UserKeyPricing | null;
  user_key_id?: string | null;
  user_key_label?: string | null;
};

type QuotaSummaryResponse = {
  available_quota: number;
  auth_type?: AuthType;
  remaining_quota?: number | null;
  ldc_balance?: number | null;
  pricing?: UserKeyPricing | null;
};

type ImageQueueStatusResponse = {
  limits: {
    per_user_waiting: number;
    global_waiting: number;
  };
  user: {
    waiting: number;
    running: number;
    active: number;
  };
  global: {
    waiting: number;
    running: number;
    active: number;
  };
  request?: ImageQueueItem | null;
  items: ImageQueueItem[];
};

export type ImageGenerationResponse = {
  id?: string;
  created: number;
  data: Array<{ b64_json: string; revised_prompt?: string; mime_type?: string; index?: number }>;
  partial_errors?: Array<{ index?: number; error?: string }>;
  billing?: ImageBilling;
  copied_text?: string;
  text_content?: string;
  conversation_id?: string;
  size?: string;
  context_mode?: string;
  retry?: {
    retryable?: boolean;
    failed_request_id?: string;
    reason?: string;
  };
};

export type UploadedInputImage = {
  id: string;
  file_id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  width?: number | null;
  height?: number | null;
  created_at?: string | null;
  client_conversation_id?: string;
  consumed_at?: string | null;
  download_url: string;
};

export type ImageRequestRecord = {
  request_id: string;
  owner_id: string;
  auth_type: AuthType | string;
  user_key_id?: string | null;
  user_key_label?: string | null;
  endpoint: string;
  protocol: string;
  model?: string | null;
  size?: string | null;
  n: number;
  stream: boolean;
  has_input_image: boolean;
  input_image_count: number;
  client_conversation_id?: string | null;
  response_id?: string | null;
  prompt_preview?: string | null;
  prompt_hash?: string | null;
  status: ImageRequestStatus;
  accepted_at?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  running_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  queue_wait_ms?: number | null;
  assigning_ms?: number | null;
  running_ms?: number | null;
  total_ms?: number | null;
  requested_count?: number | null;
  succeeded_count?: number | null;
  failed_count?: number | null;
  unit_cost?: number | null;
  charged_quota?: number | null;
  remaining_quota?: number | null;
  http_status?: number | null;
  error_type?: string | null;
  error_message?: string | null;
  upstream_error?: string | null;
  account_token_hash?: string | null;
  account_type?: string | null;
  route?: string | null;
  attempt_count?: number | null;
  fallback_used?: boolean;
  created_at: string;
};

export type ImageRequestListFilters = {
  request_id?: string;
  owner_id?: string;
  auth_type?: string;
  status?: string;
  model?: string;
  endpoint?: string;
  since?: string;
  until?: string;
  limit?: number;
  cursor?: string;
};

export type ImageConversationPayload = Record<string, unknown> & {
  id: string;
};

type ResponsesImageGenerationResponse = {
  id?: string;
  created_at?: number;
  output?: Array<{
    id?: string;
    type?: string;
    status?: string;
    result?: string;
    index?: number;
    [key: string]: unknown;
  }>;
  partial_errors?: Array<{ index?: number; error?: string }>;
  billing?: ImageBilling;
  copied_text?: string;
  text_content?: string;
  conversation_id?: string;
  metadata?: Record<string, string>;
  retry?: {
    retryable?: boolean;
    failed_request_id?: string;
    reason?: string;
  };
};

type ResponsesImageGenerationOutputItem = NonNullable<ResponsesImageGenerationResponse["output"]>[number];

type ResponsesStreamEventData = Record<string, unknown> & {
  response?: ResponsesImageGenerationResponse;
};

function isObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function toFiniteNumber(value: unknown): number | null {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function isResponsesImageGenerationOutputItem(
  value: unknown,
): value is ResponsesImageGenerationOutputItem {
  return isObjectRecord(value) && value.type === "image_generation_call";
}

function normalizeStreamImageOutputItem(
  data: ResponsesStreamEventData,
): ResponsesImageGenerationOutputItem | null {
  const rawItem = isObjectRecord(data.item) ? data.item : {};
  const itemType = String(rawItem.type || data.type || "").trim();
  const result = String(rawItem.result || data.result || "").trim();
  if (itemType !== "image_generation_call" || !result) {
    return null;
  }

  const index = toFiniteNumber(rawItem.index ?? data.index ?? data.output_index);
  return {
    ...rawItem,
    type: "image_generation_call",
    status: String(rawItem.status || "").trim() || "completed",
    result,
    ...(index !== null ? { index } : {}),
  };
}

function mergeStreamImageOutputItems(
  payload: ResponsesImageGenerationResponse,
  streamedItems: ResponsesImageGenerationOutputItem[],
): ResponsesImageGenerationResponse {
  if (streamedItems.length === 0) {
    return payload;
  }

  const output = Array.isArray(payload.output) ? [...payload.output] : [];
  const outputByIndex = new Map<number, ResponsesImageGenerationOutputItem>();
  for (const item of output) {
    if (!isResponsesImageGenerationOutputItem(item)) {
      continue;
    }
    const index = toFiniteNumber(item.index);
    if (index !== null) {
      outputByIndex.set(index, item);
    }
  }

  const mergedOutput = [...output];
  for (const streamedItem of streamedItems) {
    const index = toFiniteNumber(streamedItem.index);
    if (index === null) {
      mergedOutput.push(streamedItem);
      continue;
    }

    const existingItem = outputByIndex.get(index);
    if (existingItem) {
      const existingOutputIndex = mergedOutput.indexOf(existingItem);
      mergedOutput[existingOutputIndex] = {
        ...existingItem,
        ...streamedItem,
        result: String(streamedItem.result || existingItem.result || "").trim(),
      };
      continue;
    }

    outputByIndex.set(index, streamedItem);
    mergedOutput.push(streamedItem);
  }

  return {
    ...payload,
    output: mergedOutput,
  };
}

export async function login(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  return httpRequest<AuthSessionResponse>("/auth/login", {
    method: "POST",
    body: {},
    headers: {
      Authorization: `Bearer ${normalizedAuthKey}`,
    },
    redirectOnUnauthorized: false,
  });
}

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export async function fetchAuthSession(options: { redirectOnUnauthorized?: boolean; retries?: number } = {}) {
  const { redirectOnUnauthorized = true, retries = 0 } = options;
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await httpRequest<AuthSessionResponse>("/auth/session", {
        redirectOnUnauthorized,
      });
    } catch (error) {
      lastError = error;
      if (attempt >= retries) {
        throw error;
      }
      await wait(250 * (attempt + 1));
    }
  }

  throw lastError instanceof Error ? lastError : new Error("加载会话失败");
}

export async function fetchAccounts(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<AccountListResponse>("/api/accounts", options);
}

export async function fetchUserKeys(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<UserKeyListResponse>("/api/user-keys", options);
}

export async function fetchProxies(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<ProxyListResponse>("/api/proxies", options);
}

export async function fetchRedeemCodes(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<RedeemCodeListResponse>("/api/redeem-codes", options);
}

export async function fetchPublicGalleryItems(options: { limit?: number; redirectOnUnauthorized?: boolean } = {}) {
  const params = new URLSearchParams();
  if (options.limit) {
    params.set("limit", String(Math.max(1, options.limit)));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return httpRequest<GalleryListResponse>(`/api/gallery/public${suffix}`, {
    redirectOnUnauthorized: options.redirectOnUnauthorized,
  });
}

export async function recordGalleryItemEvent(itemId: string, event: "click" | "use") {
  return httpRequest<GalleryMutationResponse>(
    `/api/gallery/${encodeURIComponent(itemId)}/events`,
    {
      method: "POST",
      body: { event },
    },
  );
}

export async function submitGalleryItem(payload: GallerySubmissionPayload) {
  return httpRequest<GalleryMutationResponse>("/api/gallery/submissions", {
    method: "POST",
    body: payload,
  });
}

export async function fetchAdminGalleryItems(options: { status?: string; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (String(options.status || "").trim()) {
    params.set("status", String(options.status || "").trim());
  }
  if (options.limit) {
    params.set("limit", String(Math.max(1, options.limit)));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return httpRequest<GalleryListResponse>(`/api/admin/gallery${suffix}`, {
    redirectOnUnauthorized: false,
  });
}

export async function updateAdminGalleryItem(itemId: string, payload: AdminGalleryUpdatePayload) {
  return httpRequest<GalleryMutationResponse>(
    `/api/admin/gallery/${encodeURIComponent(itemId)}`,
    {
      method: "PATCH",
      body: payload,
      redirectOnUnauthorized: false,
    },
  );
}

export async function deleteAdminGalleryItem(itemId: string) {
  return httpRequest<GalleryMutationResponse>(
    `/api/admin/gallery/${encodeURIComponent(itemId)}`,
    {
      method: "DELETE",
      redirectOnUnauthorized: false,
    },
  );
}

export async function fetchDataManagementStatus(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<DataManagementStatus>("/api/data-management/status", options);
}

export async function fetchDataManagementSettings(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<DataManagementSettings>("/api/data-management/settings", options);
}

export async function updateDataManagementSettings(payload: Partial<DataManagementSettings>) {
  return httpRequest<DataManagementSettings>("/api/data-management/settings", {
    method: "PUT",
    body: payload,
  });
}

export async function createDataBackup() {
  return httpRequest<DataBackupRecord>("/api/data-management/backups", {
    method: "POST",
    body: {},
  });
}

export async function fetchDataBackups() {
  return httpRequest<{ items: DataBackupRecord[] }>("/api/data-management/backups");
}

export async function fetchDataManagementLogs() {
  return httpRequest<{ items: DataManagementLogItem[] }>("/api/data-management/logs");
}

export async function testDataManagementS3(payload: Partial<DataManagementSettings["s3"]>) {
  return httpRequest<{ ok: boolean; bucket: string }>("/api/data-management/s3/test", {
    method: "POST",
    body: payload,
  });
}

export async function fetchQuotaSummary() {
  return httpRequest<QuotaSummaryResponse>("/api/quota");
}

export async function fetchImageQueueStatus(requestId?: string | null) {
  const params = new URLSearchParams();
  if (String(requestId || "").trim()) {
    params.set("request_id", String(requestId || "").trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return httpRequest<ImageQueueStatusResponse>(`/api/image-queue/me${suffix}`);
}

export async function fetchAdminImageQueue() {
  return httpRequest<Record<string, unknown>>("/api/image-queue/admin");
}

export async function fetchImageRequests(filters: ImageRequestListFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value === undefined || value === null || String(value).trim() === "") {
      return;
    }
    params.set(key, String(value));
  });
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return httpRequest<{ items: ImageRequestRecord[]; next_cursor?: string | null }>(`/api/image-requests${suffix}`);
}

export async function fetchImageRequestRecord(requestId: string) {
  return httpRequest<ImageRequestRecord>(`/api/image-requests/${encodeURIComponent(requestId)}`);
}

export async function fetchImageConversations(
  options: { summary?: boolean; limit?: number; offset?: number } = {},
) {
  const params = new URLSearchParams();
  if (options.summary) {
    params.set("summary", "true");
  }
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.offset !== undefined) {
    params.set("offset", String(options.offset));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return httpRequest<{ items: ImageConversationPayload[] }>(`/api/image-conversations${suffix}`);
}

export async function fetchImageConversation(id: string) {
  return httpRequest<{ item: ImageConversationPayload }>(
    `/api/image-conversations/${encodeURIComponent(id)}`,
  );
}

export async function saveImageConversationToServer(conversation: ImageConversationPayload) {
  return httpRequest<{ item: ImageConversationPayload; items: ImageConversationPayload[] }>("/api/image-conversations", {
    method: "POST",
    body: conversation,
  });
}

export async function deleteImageConversationFromServer(id: string) {
  return httpRequest<{ removed: number; items: ImageConversationPayload[] }>("/api/image-conversations", {
    method: "DELETE",
    body: { id },
  });
}

export async function createAccounts(options: { tokens?: string[]; accounts?: ImportedAccount[] }) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "POST",
    body: {
      tokens: options.tokens || [],
      accounts: options.accounts || [],
    },
  });
}

export async function createDonationAccounts(options: { tokens?: string[]; accounts?: ImportedAccount[] }) {
  return httpRequest<AccountMutationResponse>("/api/donations/accounts", {
    method: "POST",
    body: {
      tokens: options.tokens || [],
      accounts: options.accounts || [],
    },
  });
}

export async function deleteAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "DELETE",
    body: { tokens },
  });
}

export async function deleteUserKeys(keys: string[]) {
  return httpRequest<UserKeyMutationResponse>("/api/user-keys", {
    method: "DELETE",
    body: { keys },
  });
}

export async function deleteRedeemCodes(codes: string[]) {
  return httpRequest<RedeemCodeMutationResponse>("/api/redeem-codes", {
    method: "DELETE",
    body: { codes },
  });
}

export async function refreshAccounts(accessTokens: string[]) {
  return httpRequest<AccountRefreshResponse>("/api/accounts/refresh", {
    method: "POST",
    body: { access_tokens: accessTokens },
  });
}

export async function updateAccount(
  accessToken: string,
  updates: {
    category?: AccountCategory;
    type?: AccountType;
    status?: AccountStatus;
    quota?: number;
  },
) {
  return httpRequest<AccountUpdateResponse>("/api/accounts/update", {
    method: "POST",
    body: {
      access_token: accessToken,
      ...updates,
    },
  });
}

export async function upsertProxy(payload: {
  id?: string;
  name?: string;
  protocol: ProxyProtocol;
  host: string;
  port: number;
  username?: string;
  password?: string;
  enabled?: boolean;
}) {
  return httpRequest<ProxyUpsertResponse>("/api/proxies", {
    method: "POST",
    body: payload,
  });
}

export async function deleteProxy(id: string) {
  return httpRequest<ProxyListResponse>("/api/proxies", {
    method: "DELETE",
    body: { id },
  });
}

export async function createUserKeys(options: {
  count: number;
  quota: number;
  prefix?: string;
  label_prefix?: string;
  status?: UserKeyStatus;
  pricing?: UserKeyPricing;
}) {
  return httpRequest<UserKeyMutationResponse>("/api/user-keys", {
    method: "POST",
    body: options,
  });
}

export async function createRedeemCodes(options: {
  count: number;
  target_quota: number;
  prefix?: string;
  label?: string;
}) {
  return httpRequest<RedeemCodeMutationResponse>("/api/redeem-codes", {
    method: "POST",
    body: options,
  });
}

export async function updateUserKey(
  key: string,
  updates: {
    label?: string;
    quota?: number;
    ldc_balance?: number;
    status?: UserKeyStatus;
    pricing?: UserKeyPricing;
  },
) {
  return httpRequest<UserKeyUpdateResponse>("/api/user-keys/update", {
    method: "POST",
    body: {
      key,
      ...updates,
    },
  });
}

export async function purchaseQuota(packageCount = 1) {
  return httpRequest<RedeemCodeMutationResponse>("/api/quota/purchase", {
    method: "POST",
    body: { package_count: Math.max(1, packageCount) },
  });
}

export async function redeemCode(code: string) {
  return httpRequest<RedeemCodeMutationResponse>("/api/redeem-codes/redeem", {
    method: "POST",
    body: { code },
  });
}

function normalizeResponsesImageGenerationResponse(
  payload: ResponsesImageGenerationResponse,
): ImageGenerationResponse {
  const data = Array.isArray(payload.output)
    ? payload.output
        .filter((item) => item?.type === "image_generation_call" && String(item.result || "").trim())
        .map((item) => ({
          b64_json: String(item?.result || "").trim(),
          ...(Number.isFinite(Number(item?.index)) ? { index: Number(item?.index) } : {}),
        }))
    : [];
  return {
    created: Math.max(0, Number(payload.created_at || 0)) || Math.floor(Date.now() / 1000),
    id: String(payload.id || "").trim() || undefined,
    data,
    partial_errors: Array.isArray(payload.partial_errors)
      ? payload.partial_errors.map((item) => ({
          ...(Number.isFinite(Number(item?.index)) ? { index: Number(item?.index) } : {}),
          error: String(item?.error || "").trim() || undefined,
        }))
      : undefined,
    billing: payload.billing,
    copied_text: String(payload.copied_text || "").trim() || undefined,
    text_content: String(payload.text_content || "").trim() || undefined,
    conversation_id: String(payload.conversation_id || "").trim() || undefined,
    size: String(payload.metadata?.size || "").trim() || undefined,
    context_mode: String(payload.metadata?.context_mode || "").trim() || undefined,
    retry: payload.retry
      ? {
          retryable: Boolean(payload.retry.retryable),
          failed_request_id: String(payload.retry.failed_request_id || "").trim() || undefined,
          reason: String(payload.retry.reason || "").trim() || undefined,
        }
      : undefined,
  };
}

function parseResponsesStreamEvent(rawEvent: string) {
  let event = "";
  const dataLines: string[] = [];
  for (const line of rawEvent.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  const dataText = dataLines.join("\n").trim();
  if (!dataText || dataText === "[DONE]") {
    return { event, data: dataText };
  }
  return { event, data: JSON.parse(dataText) as Record<string, unknown> };
}

function isResponsesStreamEventData(value: unknown): value is ResponsesStreamEventData {
  return typeof value === "object" && value !== null;
}

async function readResponsesImageGenerationStream(response: Response) {
  return readResponsesImageGenerationStreamWithCallbacks(response);
}

async function readResponsesImageGenerationStreamWithCallbacks(
  response: Response,
  options: {
    onResponseId?: (responseId: string) => void;
  } = {},
) {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("响应流不可用");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  let completedPayload: ResponsesImageGenerationResponse | null = null;
  const streamedItemsByIndex = new Map<number, ResponsesImageGenerationOutputItem>();
  const streamedItemsWithoutIndex: ResponsesImageGenerationOutputItem[] = [];

  const recordStreamedItem = (item: ResponsesImageGenerationOutputItem | null) => {
    if (!item) {
      return;
    }
    const index = toFiniteNumber(item.index);
    if (index === null) {
      streamedItemsWithoutIndex.push(item);
      return;
    }
    streamedItemsByIndex.set(index, item);
  };

  const processRawEvent = (rawEvent: string) => {
    if (!rawEvent.trim()) {
      return;
    }
    const parsed = parseResponsesStreamEvent(rawEvent);
    if (!isResponsesStreamEventData(parsed.data)) {
      return;
    }
    if (parsed.event === "response.created") {
      const createdResponse = parsed.data.response as { id?: string } | undefined;
      const responseId = String(createdResponse?.id || "").trim();
      if (responseId) {
        options.onResponseId?.(responseId);
      }
      return;
    }
    if (parsed.event === "response.completed") {
      completedPayload = parsed.data.response || null;
      const responseId = String(completedPayload?.id || "").trim();
      if (responseId) {
        options.onResponseId?.(responseId);
      }
      return;
    }
    if (
      parsed.event === "response.image_generation_call.completed" ||
      parsed.event === "response.output_item.done"
    ) {
      recordStreamedItem(normalizeStreamImageOutputItem(parsed.data));
      return;
    }
    if (parsed.event === "response.failed") {
      const failedResponse = parsed.data.response as { error?: { message?: string } };
      throw new Error(String(failedResponse?.error?.message || "").trim() || "生成图片失败");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      const events = buffer.split(/\n\n/);
      buffer = events.pop() || "";
      for (const rawEvent of events) {
        processRawEvent(rawEvent);
      }
    }
    if (done) {
      break;
    }
  }
  processRawEvent(buffer);

  if (!completedPayload) {
    throw new Error("生成响应没有结束信号");
  }
  return mergeStreamImageOutputItems(completedPayload, [
    ...streamedItemsByIndex.values(),
    ...streamedItemsWithoutIndex,
  ]);
}

export async function generateImage(
  prompt: string,
  model: ImageModel = "gpt-image-2",
  n = 1,
  options: {
    inputImageUrl?: string | null;
    inputImageFileId?: string | null;
    queueRequestId?: string | null;
    clientConversationId?: string | null;
    previousResponseId?: string | null;
    size?: string | null;
    onResponseId?: (responseId: string) => void;
    headers?: Record<string, string>;
  } = {},
) {
  const inputImageUrl = String(options.inputImageUrl || "").trim();
  const inputImageFileId = String(options.inputImageFileId || "").trim();
  const queueRequestId = String(options.queueRequestId || "").trim();
  const clientConversationId = String(options.clientConversationId || "").trim();
  const previousResponseId = String(options.previousResponseId || "").trim();
  const size = String(options.size || "auto").trim() || "auto";
  const imageGenerationTool =
    size.toLowerCase() === "auto"
      ? { type: "image_generation", model }
      : { type: "image_generation", model, size };
  const queueHeaders = queueRequestId ? {"X-Image-Queue-Request-Id": queueRequestId} : undefined;
  const inputItems: Array<
    | { type: "input_text"; text: string }
    | { type: "input_image"; file_id: string }
    | { type: "input_image"; image_url: string }
  > = [{ type: "input_text", text: prompt }];
  if (inputImageFileId) {
    inputItems.push({ type: "input_image", file_id: inputImageFileId });
  } else if (inputImageUrl) {
    inputItems.push({ type: "input_image", image_url: inputImageUrl });
  }

  const body = {
      model: "gpt-5",
      input: inputItems,
      tools: [imageGenerationTool],
      tool_choice: { type: "image_generation" },
      ...(previousResponseId ? { previous_response_id: previousResponseId } : {}),
      n,
      stream: true,
      metadata: clientConversationId
        ? { client_conversation_id: clientConversationId }
        : undefined,
  };
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(queueHeaders || {}),
    ...(options.headers || {}),
  };
  const response = await httpStreamRequest("/v1/responses", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const payload = await readResponsesImageGenerationStreamWithCallbacks(response, {
    onResponseId: options.onResponseId,
  });
  const responseId = String(payload.id || "").trim();
  if (responseId) {
    options.onResponseId?.(responseId);
  }
  return normalizeResponsesImageGenerationResponse(payload);
}

export async function fetchImageResponseResult(responseId: string) {
  const normalizedId = String(responseId || "").trim();
  if (!normalizedId) {
    throw new Error("缺少 response_id");
  }
  const payload = await httpRequest<ResponsesImageGenerationResponse>(
    `/v1/responses/${encodeURIComponent(normalizedId)}`,
  );
  return normalizeResponsesImageGenerationResponse(payload);
}

export async function uploadInputImage(file: File, clientConversationId: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("client_conversation_id", String(clientConversationId || "").trim());
  return httpRequest<UploadedInputImage>("/backend-api/files/process_upload_stream", {
    method: "POST",
    body: formData,
  });
}

export async function listRecentUploadedImages(
  limit = 25,
  imagesAppOnly = false,
  clientConversationId?: string | null,
) {
  const params = new URLSearchParams({
    limit: String(limit),
    images_app_only: String(imagesAppOnly),
  });
  if (String(clientConversationId || "").trim()) {
    params.set("client_conversation_id", String(clientConversationId || "").trim());
  }
  return httpRequest<{ items: UploadedInputImage[] }>(`/backend-api/my/recent/uploaded_images?${params.toString()}`);
}
