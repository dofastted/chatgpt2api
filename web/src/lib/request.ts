import axios, {AxiosError, type AxiosRequestConfig} from "axios";

import webConfig from "@/constants/common-env";
import {clearStoredAuthKey, getStoredAuthKey} from "@/store/auth";

type RequestConfig = AxiosRequestConfig & {
    redirectOnUnauthorized?: boolean;
};

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

const request = axios.create();

function buildRequestHeaders(headers?: Record<string, string>, authKey?: string) {
    const nextHeaders = {...(headers || {})};
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

request.interceptors.request.use(async (config) => {
    const nextConfig = {...config};
    const authKey = await getStoredAuthKey();
    const headers = buildRequestHeaders(nextConfig.headers as Record<string, string> | undefined, authKey);
    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
    // @ts-expect-error
    nextConfig.headers = headers;
    return nextConfig;
});

request.interceptors.response.use(
    (response) => response,
    async (
        error: AxiosError<{
            detail?: { error?: string } | Array<{ msg?: string }>;
            error?: string;
            message?: string;
        }>,
    ) => {
        const status = error.response?.status;
        const shouldRedirect = (error.config as RequestConfig | undefined)?.redirectOnUnauthorized !== false;
        if (status === 401 && shouldRedirect && typeof window !== "undefined") {
            await clearStoredAuthKey();
            window.location.href = "/login";
        }

        const payload = error.response?.data;
        const message = getPayloadErrorMessage(payload, error.message || `请求失败 (${status || 500})`);
        return Promise.reject(new Error(message));
    },
);

export async function httpRequest<T>(path: string, options: RequestOptions = {}) {
    const {method = "GET", body, headers, redirectOnUnauthorized = true} = options;
    const config: RequestConfig = {
        baseURL: webConfig.apiUrl.replace(/\/$/, ""),
        url: path,
        method,
        data: body,
        headers,
        redirectOnUnauthorized,
    };
    const response = await request.request<T>(config);
    return response.data;
}

export async function httpStreamRequest(path: string, options: StreamRequestOptions = {}) {
    const {method = "GET", body, headers, redirectOnUnauthorized = true} = options;
    const authKey = await getStoredAuthKey();
    const response = await fetch(`${webConfig.apiUrl.replace(/\/$/, "")}${path}`, {
        method,
        headers: buildRequestHeaders(headers, authKey),
        body,
    });

    if (response.status === 401 && redirectOnUnauthorized && typeof window !== "undefined") {
        await clearStoredAuthKey();
        window.location.href = "/login";
    }

    if (!response.ok) {
        const fallback = `请求失败 (${response.status || 500})`;
        let payload: ErrorPayload | undefined;
        try {
            payload = (await response.json()) as ErrorPayload;
        } catch {
            throw new Error(fallback);
        }
        throw new Error(getPayloadErrorMessage(payload, fallback));
    }

    return response;
}
