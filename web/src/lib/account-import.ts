const DIRECT_TOKEN_KEYS = new Set([
  "access_token",
  "accesstoken",
  "chatgpt_access_token",
  "chatgptaccesstoken",
  "session_token",
  "sessiontoken",
]);

const FALLBACK_TOKEN_KEYS = new Set(["token"]);

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

export function cleanJsonText(text: string) {
  return text.replace(/^\uFEFF/, "").trim();
}
