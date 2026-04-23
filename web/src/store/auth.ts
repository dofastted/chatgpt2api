"use client";

import localforage from "localforage";

export const AUTH_KEY_STORAGE_KEY = "chatgpt2api_auth_key";

const authStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "auth",
});
let memoryAuthKey = "";

function readLocalStorageAuthKey() {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    return String(window.localStorage.getItem(AUTH_KEY_STORAGE_KEY) || "").trim();
  } catch {
    return "";
  }
}

function writeLocalStorageAuthKey(authKey: string) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (authKey) {
      window.localStorage.setItem(AUTH_KEY_STORAGE_KEY, authKey);
    } else {
      window.localStorage.removeItem(AUTH_KEY_STORAGE_KEY);
    }
  } catch {
    return;
  }
}

export async function getStoredAuthKey() {
  if (typeof window === "undefined") {
    return "";
  }
  if (memoryAuthKey) {
    return memoryAuthKey;
  }
  const localStorageValue = readLocalStorageAuthKey();
  if (localStorageValue) {
    memoryAuthKey = localStorageValue;
    return localStorageValue;
  }
  try {
    const value = await authStorage.getItem<string>(AUTH_KEY_STORAGE_KEY);
    const normalizedValue = String(value || "").trim();
    if (normalizedValue) {
      memoryAuthKey = normalizedValue;
      writeLocalStorageAuthKey(normalizedValue);
    }
    return normalizedValue;
  } catch {
    return "";
  }
}

export async function setStoredAuthKey(authKey: string) {
  const normalizedAuthKey = String(authKey || "").trim();
  if (!normalizedAuthKey) {
    await clearStoredAuthKey();
    return;
  }
  memoryAuthKey = normalizedAuthKey;
  writeLocalStorageAuthKey(normalizedAuthKey);
  try {
    await authStorage.setItem(AUTH_KEY_STORAGE_KEY, normalizedAuthKey);
  } catch {
    return;
  }
}

export async function clearStoredAuthKey() {
  if (typeof window === "undefined") {
    return;
  }
  memoryAuthKey = "";
  writeLocalStorageAuthKey("");
  try {
    await authStorage.removeItem(AUTH_KEY_STORAGE_KEY);
  } catch {
    return;
  }
}
