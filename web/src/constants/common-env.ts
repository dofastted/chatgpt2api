const LOCAL_DEV_API_URL = "http://127.0.0.1:8000";

function trimTrailingSlash(value: string) {
  return String(value || "").trim().replace(/\/$/, "");
}

function resolveBrowserApiUrl() {
  if (typeof window === "undefined") {
    return "";
  }
  const { hostname, origin, port } = window.location;
  const isLoopbackHost = hostname === "127.0.0.1" || hostname === "localhost";
  const isNextDevOrigin = isLoopbackHost && port === "3000";
  if (process.env.NODE_ENV === "development" && isNextDevOrigin) {
    return LOCAL_DEV_API_URL;
  }
  return origin;
}

export function resolveApiUrl() {
  const configuredApiUrl = trimTrailingSlash(process.env.NEXT_PUBLIC_API_URL || "");
  if (configuredApiUrl) {
    return configuredApiUrl;
  }
  const browserApiUrl = trimTrailingSlash(resolveBrowserApiUrl());
  if (browserApiUrl) {
    return browserApiUrl;
  }
  if (process.env.NODE_ENV === "development") {
    return LOCAL_DEV_API_URL;
  }
  return "";
}

const webConfig = {
  get apiUrl() {
    return resolveApiUrl();
  },
  appVersion: process.env.NEXT_PUBLIC_APP_VERSION || "0.0.0",
};

export default webConfig;
