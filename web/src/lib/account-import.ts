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
  return key.replace(/[\s-]+/g, "_").toLowerCase() === "access_token";
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
      if (token) {
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
