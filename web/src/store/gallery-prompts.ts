"use client";

import localforage from "localforage";

export type UserGalleryPrompt = {
  id: string;
  prompt: string;
  promptPreview: string;
  useCount: number;
  createdAt: string;
  updatedAt: string;
};

export type GalleryPromptStats = Record<string, number>;

export type UserGalleryWaterfallItem = {
  id: string;
  prompt: string;
  promptPreview: string;
  imageUrl: string;
  mimeType?: string;
  width?: number;
  height?: number;
  aspectRatio?: number;
  createdAt: string;
  updatedAt: string;
  sourceConversationId?: string;
  sourceTurnId?: string;
  sourceImageId?: string;
};

const galleryPromptStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "gallery_prompts",
});

const USER_PROMPTS_KEY_PREFIX = "user_prompts";
const USER_WATERFALL_ITEMS_KEY_PREFIX = "user_waterfall_items";
const PROMPT_STATS_KEY_PREFIX = "prompt_stats";
const DEFAULT_SCOPE = "__anonymous__";

function normalizeScope(scope: string | null | undefined) {
  return String(scope || "").trim() || DEFAULT_SCOPE;
}

function userPromptsKey(scope: string | null | undefined) {
  return `${USER_PROMPTS_KEY_PREFIX}:${normalizeScope(scope)}`;
}

function userWaterfallItemsKey(scope: string | null | undefined) {
  return `${USER_WATERFALL_ITEMS_KEY_PREFIX}:${normalizeScope(scope)}`;
}

function promptStatsKey(scope: string | null | undefined) {
  return `${PROMPT_STATS_KEY_PREFIX}:${normalizeScope(scope)}`;
}

export function normalizeGalleryPrompt(prompt: string) {
  return String(prompt || "").replace(/\s+/g, " ").trim();
}

export function buildPromptPreview(prompt: string, limit = 120) {
  const normalized = normalizeGalleryPrompt(prompt);
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

export function promptKey(prompt: string) {
  const normalized = normalizeGalleryPrompt(prompt).toLowerCase();
  let hash = 2166136261;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function createPromptId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `prompt-${crypto.randomUUID()}`;
  }
  return `prompt-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createWaterfallItemId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `waterfall-${crypto.randomUUID()}`;
  }
  return `waterfall-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeUserPrompt(value: UserGalleryPrompt): UserGalleryPrompt | null {
  const prompt = normalizeGalleryPrompt(value?.prompt || "");
  if (!prompt) {
    return null;
  }
  const now = new Date().toISOString();
  return {
    id: String(value?.id || "").trim() || createPromptId(),
    prompt,
    promptPreview: buildPromptPreview(value?.promptPreview || prompt),
    useCount: Math.max(0, Number(value?.useCount || 0)),
    createdAt: String(value?.createdAt || "").trim() || now,
    updatedAt: String(value?.updatedAt || "").trim() || now,
  };
}

function normalizeUserWaterfallItem(
  value: UserGalleryWaterfallItem,
): UserGalleryWaterfallItem | null {
  const imageUrl = String(value?.imageUrl || "").trim();
  if (!imageUrl) {
    return null;
  }
  const prompt = normalizeGalleryPrompt(value?.prompt || "");
  const now = new Date().toISOString();
  const width = Math.max(0, Number(value?.width || 0)) || undefined;
  const height = Math.max(0, Number(value?.height || 0)) || undefined;
  const storedAspectRatio = Math.max(0, Number(value?.aspectRatio || 0));
  const aspectRatio =
    storedAspectRatio || (width && height ? width / height : undefined);
  return {
    id: String(value?.id || "").trim() || createWaterfallItemId(),
    prompt,
    promptPreview: buildPromptPreview(value?.promptPreview || prompt),
    imageUrl,
    mimeType: String(value?.mimeType || "").trim() || undefined,
    width,
    height,
    aspectRatio,
    createdAt: String(value?.createdAt || "").trim() || now,
    updatedAt: String(value?.updatedAt || "").trim() || now,
    sourceConversationId:
      String(value?.sourceConversationId || "").trim() || undefined,
    sourceTurnId: String(value?.sourceTurnId || "").trim() || undefined,
    sourceImageId: String(value?.sourceImageId || "").trim() || undefined,
  };
}

export async function listUserGalleryPrompts(scope: string | null | undefined) {
  const stored = await galleryPromptStorage.getItem<UserGalleryPrompt[]>(userPromptsKey(scope));
  const items = Array.isArray(stored) ? stored : [];
  return items
    .map((item) => normalizeUserPrompt(item))
    .filter((item): item is UserGalleryPrompt => Boolean(item))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function listUserGalleryWaterfallItems(
  scope: string | null | undefined,
) {
  const stored = await galleryPromptStorage.getItem<UserGalleryWaterfallItem[]>(
    userWaterfallItemsKey(scope),
  );
  const items = Array.isArray(stored) ? stored : [];
  return items
    .map((item) => normalizeUserWaterfallItem(item))
    .filter((item): item is UserGalleryWaterfallItem => Boolean(item))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function addUserGalleryPrompt(scope: string | null | undefined, prompt: string) {
  const normalizedPrompt = normalizeGalleryPrompt(prompt);
  if (!normalizedPrompt) {
    throw new Error("请输入 prompt");
  }
  const items = await listUserGalleryPrompts(scope);
  const key = promptKey(normalizedPrompt);
  const existing = items.find((item) => promptKey(item.prompt) === key);
  const now = new Date().toISOString();
  const nextItem: UserGalleryPrompt = existing
    ? {
        ...existing,
        prompt: normalizedPrompt,
        promptPreview: buildPromptPreview(normalizedPrompt),
        updatedAt: now,
      }
    : {
        id: createPromptId(),
        prompt: normalizedPrompt,
        promptPreview: buildPromptPreview(normalizedPrompt),
        useCount: 0,
        createdAt: now,
        updatedAt: now,
      };
  const nextItems = [nextItem, ...items.filter((item) => item.id !== nextItem.id)]
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  await galleryPromptStorage.setItem(userPromptsKey(scope), nextItems);
  return nextItem;
}

export async function addUserGalleryWaterfallItem(
  scope: string | null | undefined,
  input: Omit<UserGalleryWaterfallItem, "id" | "createdAt" | "updatedAt"> & {
    id?: string;
    createdAt?: string;
    updatedAt?: string;
  },
) {
  const imageUrl = String(input.imageUrl || "").trim();
  if (!imageUrl) {
    throw new Error("图片为空，无法添加");
  }
  const items = await listUserGalleryWaterfallItems(scope);
  const normalizedSourceImageId = String(input.sourceImageId || "").trim();
  const existing = normalizedSourceImageId
    ? items.find((item) => item.sourceImageId === normalizedSourceImageId)
    : null;
  const now = new Date().toISOString();
  const nextItem = normalizeUserWaterfallItem({
    ...input,
    id: existing?.id || input.id || createWaterfallItemId(),
    imageUrl,
    createdAt: now,
    updatedAt: now,
  });
  if (!nextItem) {
    throw new Error("图片为空，无法添加");
  }
  const nextItems = [
    nextItem,
    ...items.filter((item) => item.id !== nextItem.id),
  ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  await galleryPromptStorage.setItem(userWaterfallItemsKey(scope), nextItems);
  return nextItem;
}

export async function removeUserGalleryPrompt(scope: string | null | undefined, promptId: string) {
  const normalizedId = String(promptId || "").trim();
  if (!normalizedId) {
    return;
  }
  const items = await listUserGalleryPrompts(scope);
  await galleryPromptStorage.setItem(
    userPromptsKey(scope),
    items.filter((item) => item.id !== normalizedId),
  );
}

export async function loadGalleryPromptStats(scope: string | null | undefined): Promise<GalleryPromptStats> {
  const stored = await galleryPromptStorage.getItem<GalleryPromptStats>(promptStatsKey(scope));
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(stored).map(([key, value]) => [key, Math.max(0, Number(value || 0))]),
  );
}

export async function recordGalleryPromptUse(scope: string | null | undefined, prompt: string) {
  const normalizedPrompt = normalizeGalleryPrompt(prompt);
  if (!normalizedPrompt) {
    return;
  }
  const key = promptKey(normalizedPrompt);
  const [items, stats] = await Promise.all([
    listUserGalleryPrompts(scope),
    loadGalleryPromptStats(scope),
  ]);
  const nextStats = {
    ...stats,
    [key]: Math.max(0, Number(stats[key] || 0)) + 1,
  };
  const nextItems = items.map((item) =>
    promptKey(item.prompt) === key
      ? { ...item, useCount: nextStats[key], updatedAt: new Date().toISOString() }
      : item,
  );
  await Promise.all([
    galleryPromptStorage.setItem(promptStatsKey(scope), nextStats),
    galleryPromptStorage.setItem(userPromptsKey(scope), nextItems),
  ]);
}
