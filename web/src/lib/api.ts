import { httpRequest } from "@/lib/request";

export type AccountType = "Free" | "Plus" | "Pro" | "Team";
export type AccountStatus = "正常" | "限流" | "异常" | "禁用";
export type AccountCategory = "普通" | "捐赠";
export type ImageModel = "gpt-image-1" | "gpt-image-2";
export type AuthRole = "user" | "admin";
export type AuthType = "auth_key" | "admin_auth_key" | "user_key";
export type UserKeyStatus = "启用" | "停用";

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
};

export type UserKey = {
  id: string;
  key: string;
  label?: string | null;
  quota: number;
  status: UserKeyStatus;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastUsedAt?: string | null;
};

type AccountListResponse = {
  items: Account[];
};

type UserKeyListResponse = {
  items: UserKey[];
};

type AccountMutationResponse = {
  items: Account[];
  added?: number;
  skipped?: number;
  removed?: number;
  refreshed?: number;
  rewarded_accounts?: number;
  rewarded_quota?: number;
  remaining_quota?: number | null;
  errors?: Array<{ access_token: string; error: string }>;
};

type UserKeyMutationResponse = {
  items: UserKey[];
  created_items?: UserKey[];
  added?: number;
  removed?: number;
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
  user_key_id?: string | null;
  user_key_label?: string | null;
};

type QuotaSummaryResponse = {
  available_quota: number;
  auth_type?: AuthType;
  remaining_quota?: number | null;
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

export async function fetchAuthSession() {
  return httpRequest<AuthSessionResponse>("/auth/session");
}

export async function fetchAccounts() {
  return httpRequest<AccountListResponse>("/api/accounts");
}

export async function fetchUserKeys() {
  return httpRequest<UserKeyListResponse>("/api/user-keys");
}

export async function fetchQuotaSummary() {
  return httpRequest<QuotaSummaryResponse>("/api/quota");
}

export async function createAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/accounts", {
    method: "POST",
    body: { tokens },
  });
}

export async function createDonationAccounts(tokens: string[]) {
  return httpRequest<AccountMutationResponse>("/api/donations/accounts", {
    method: "POST",
    body: { tokens },
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
}) {
  return httpRequest<UserKeyMutationResponse>("/api/user-keys", {
    method: "POST",
    body: options,
  });
}

export async function updateUserKey(
  key: string,
  updates: {
    label?: string;
    quota?: number;
    status?: UserKeyStatus;
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

export async function generateImage(prompt: string, model: ImageModel = "gpt-image-1", n = 1) {
  return httpRequest<{ created: number; data: Array<{ b64_json: string; revised_prompt?: string }> }>(
    "/v1/images/generations",
    {
      method: "POST",
      body: {
        prompt,
        model,
        n,
        response_format: "b64_json",
      },
    },
  );
}
