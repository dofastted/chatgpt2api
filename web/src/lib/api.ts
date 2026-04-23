import { httpRequest } from "@/lib/request";

export type AccountType = "Free" | "Plus" | "Pro" | "Team";
export type AccountStatus = "正常" | "限流" | "异常" | "禁用";
export type AccountCategory = "普通" | "捐赠";
export type ImageModel = "gpt-image-1" | "gpt-image-2";
export type AuthRole = "user" | "admin";
export type AuthType = "auth_key" | "admin_auth_key" | "user_key";
export type UserKeyStatus = "启用" | "停用";
export type UserKeyPricing = {
  "gpt-image-1": number;
  "gpt-image-2": number;
};

export type ImageBilling = {
  requested_model: ImageModel;
  unit_cost: number;
  charged_quota: number;
  remaining_quota: number;
};

export type ImageQueueItemStatus = "waiting" | "assigning_account" | "running" | "finished" | "failed";

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

type AccountListResponse = {
  items: Account[];
};

type UserKeyListResponse = {
  items: UserKey[];
};

type RedeemCodeListResponse = {
  items: RedeemCode[];
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
  };
  global: {
    waiting: number;
    running: number;
  };
  request?: ImageQueueItem | null;
  items: ImageQueueItem[];
};

export type ImageGenerationResponse = {
  created: number;
  data: Array<{ b64_json: string; revised_prompt?: string; mime_type?: string }>;
  billing?: ImageBilling;
  copied_text?: string;
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
  download_url: string;
};

type ResponsesImageGenerationResponse = {
  created_at?: number;
  output?: Array<{
    type?: string;
    status?: string;
    result?: string;
  }>;
  billing?: ImageBilling;
  copied_text?: string;
};

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

export async function fetchRedeemCodes(options: { redirectOnUnauthorized?: boolean } = {}) {
  return httpRequest<RedeemCodeListResponse>("/api/redeem-codes", options);
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
        }))
    : [];
  return {
    created: Math.max(0, Number(payload.created_at || 0)) || Math.floor(Date.now() / 1000),
    data,
    billing: payload.billing,
    copied_text: String(payload.copied_text || "").trim() || undefined,
  };
}

export async function generateImage(
  prompt: string,
  model: ImageModel = "gpt-image-2",
  n = 1,
  options: { inputImageUrl?: string | null; inputImageFileId?: string | null; queueRequestId?: string | null } = {},
) {
  const inputImageUrl = String(options.inputImageUrl || "").trim();
  const inputImageFileId = String(options.inputImageFileId || "").trim();
  const queueRequestId = String(options.queueRequestId || "").trim();
  const queueHeaders = queueRequestId ? {"X-Image-Queue-Request-Id": queueRequestId} : undefined;
  if (!inputImageUrl && !inputImageFileId) {
    return httpRequest<ImageGenerationResponse>("/v1/images/generations", {
      method: "POST",
      body: {
        prompt,
        model,
        n,
        response_format: "b64_json",
      },
      headers: queueHeaders,
    });
  }

  const payload = await httpRequest<ResponsesImageGenerationResponse>("/v1/responses", {
    method: "POST",
    body: {
      model: "gpt-5",
      input: [
        { type: "input_text", text: prompt },
        inputImageFileId
          ? { type: "input_image", file_id: inputImageFileId }
          : { type: "input_image", image_url: inputImageUrl },
      ],
      tools: [{ type: "image_generation", model }],
      n,
    },
    headers: queueHeaders,
  });
  return normalizeResponsesImageGenerationResponse(payload);
}

export async function uploadInputImage(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return httpRequest<UploadedInputImage>("/backend-api/files/process_upload_stream", {
    method: "POST",
    body: formData,
  });
}

export async function listRecentUploadedImages(limit = 25, imagesAppOnly = false) {
  const params = new URLSearchParams({
    limit: String(limit),
    images_app_only: String(imagesAppOnly),
  });
  return httpRequest<{ items: UploadedInputImage[] }>(`/backend-api/my/recent/uploaded_images?${params.toString()}`);
}
