import webConfig from "@/constants/common-env";
import { clearStoredAuthKey, getStoredAuthKey } from "@/store/auth";

type RequestOptions = {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  redirectOnUnauthorized?: boolean;
};

type StreamRequestOptions = RequestOptions & {
  body?: BodyInit | null;
};

type ErrorPayload = {
  detail?: { error?: string } | Array<{ msg?: string }>;
  error?: string;
  message?: string;
};

function buildRequestHeaders(headers?: Record<string, string>, authKey?: string) {
  const nextHeaders = { ...(headers || {}) };
  if (authKey && !nextHeaders.Authorization) {
    nextHeaders.Authorization = `Bearer ${authKey}`;
  }
  return nextHeaders;
}

function getPayloadErrorMessage(payload: ErrorPayload | undefined, fallback: string) {
  const validationMessage = Array.isArray(payload?.detail)
    ? payload.detail
        .map((item) => String(item?.msg || "").trim())
        .filter(Boolean)
        .join("；")
    : "";
  return (
    (!Array.isArray(payload?.detail) ? payload?.detail?.error : "") ||
    validationMessage ||
    payload?.error ||
    payload?.message ||
    fallback
  );
}

async function redirectToLoginIfNeeded(response: Response, redirectOnUnauthorized: boolean) {
  if (response.status !== 401 || !redirectOnUnauthorized || typeof window === "undefined") {
    return;
  }
  await clearStoredAuthKey();
  window.location.href = "/login";
}

async function readErrorPayload(response: Response, fallback: string) {
  try {
    return getPayloadErrorMessage((await response.json()) as ErrorPayload, fallback);
  } catch {
    return fallback;
  }
}

export async function httpRequest<T>(path: string, options: RequestOptions = {}) {
  const { method = "GET", body, headers, redirectOnUnauthorized = true } = options;
  const authKey = await getStoredAuthKey();
  const nextHeaders = buildRequestHeaders(headers, authKey);
  const requestInit: RequestInit = {
    method,
    headers: nextHeaders,
  };

  if (body !== undefined) {
    if (!nextHeaders["Content-Type"] && !nextHeaders["content-type"]) {
      nextHeaders["Content-Type"] = "application/json";
    }
    requestInit.body = JSON.stringify(body);
  }

  const response = await fetch(`${webConfig.apiUrl.replace(/\/$/, "")}${path}`, requestInit);
  await redirectToLoginIfNeeded(response, redirectOnUnauthorized);

  if (!response.ok) {
    const fallback = `请求失败 (${response.status || 500})`;
    throw new Error(await readErrorPayload(response, fallback));
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as T;
  }
}

export async function httpStreamRequest(path: string, options: StreamRequestOptions = {}) {
  const { method = "GET", body, headers, redirectOnUnauthorized = true } = options;
  const authKey = await getStoredAuthKey();
  const response = await fetch(`${webConfig.apiUrl.replace(/\/$/, "")}${path}`, {
    method,
    headers: buildRequestHeaders(headers, authKey),
    body,
  });

  await redirectToLoginIfNeeded(response, redirectOnUnauthorized);

  if (!response.ok) {
    const fallback = `请求失败 (${response.status || 500})`;
    throw new Error(await readErrorPayload(response, fallback));
  }

  return response;
}
