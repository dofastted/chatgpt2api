const DIRECT_TOKEN_KEYS = new Set([
  "access_token",
  "accesstoken",
  "chatgpt_access_token",
  "chatgptaccesstoken",
  "session_token",
  "sessiontoken",
]);

const FALLBACK_TOKEN_KEYS = new Set(["token"]);

export type ImportedAccountEntry = {
  access_token: string;
  [key: string]: unknown;
};

function normalizeKey(key: string) {
  return key.replace(/[\s-]+/g, "_").toLowerCase();
}

function looksLikeAccessToken(value: string) {
  const token = String(value || "").trim();
  if (!token) {
    return false;
  }
  if (token.startsWith("eyJ") && token.split(".").length >= 3) {
    return true;
  }
  return token.length >= 40;
}

export function normalizeTokenList(tokens: string[]) {
  return Array.from(
    new Set(
      tokens
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function isAccessTokenKey(key: string) {
  const normalizedKey = normalizeKey(key);
  return DIRECT_TOKEN_KEYS.has(normalizedKey) || FALLBACK_TOKEN_KEYS.has(normalizedKey);
}

function readAccountToken(value: Record<string, unknown>) {
  for (const [key, item] of Object.entries(value)) {
    if (!isAccessTokenKey(key)) {
      continue;
    }
    const token = String(item || "").trim();
    if (!token) {
      continue;
    }
    const normalizedKey = normalizeKey(key);
    const shouldCollect = DIRECT_TOKEN_KEYS.has(normalizedKey) ? true : looksLikeAccessToken(token);
    if (shouldCollect) {
      return token;
    }
  }
  return "";
}

function collectAccessTokens(value: unknown, collected: string[]) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectAccessTokens(item, collected));
    return;
  }

  if (!value || typeof value !== "object") {
    return;
  }

  Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
    if (isAccessTokenKey(key)) {
      const token = String(item || "").trim();
      const normalizedKey = normalizeKey(key);
      const shouldCollect = DIRECT_TOKEN_KEYS.has(normalizedKey) ? Boolean(token) : looksLikeAccessToken(token);
      if (shouldCollect) {
        collected.push(token);
      }
      return;
    }

    collectAccessTokens(item, collected);
  });
}

export function extractAccessTokensFromJson(value: unknown) {
  const collected: string[] = [];
  collectAccessTokens(value, collected);
  return normalizeTokenList(collected);
}

function collectAccountEntries(value: unknown, collected: ImportedAccountEntry[]) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectAccountEntries(item, collected));
    return;
  }

  if (!value || typeof value !== "object") {
    return;
  }

  const record = value as Record<string, unknown>;
  const token = readAccountToken(record);
  if (token) {
    collected.push({
      ...record,
      access_token: token,
    });
  }

  Object.values(record).forEach((item) => {
    collectAccountEntries(item, collected);
  });
}

export function extractAccountsFromJson(value: unknown) {
  const collected: ImportedAccountEntry[] = [];
  collectAccountEntries(value, collected);
  const indexed = new Map<string, ImportedAccountEntry>();
  collected.forEach((item) => {
    const accessToken = String(item.access_token || "").trim();
    if (!accessToken) {
      return;
    }
    indexed.set(accessToken, {
      ...indexed.get(accessToken),
      ...item,
      access_token: accessToken,
    });
  });
  return Array.from(indexed.values());
}

export function cleanJsonText(text: string) {
  return text.replace(/^\uFEFF/, "").trim();
}
