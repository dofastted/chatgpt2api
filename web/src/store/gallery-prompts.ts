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
  assets?: UserGalleryWaterfallAsset[];
  coverAssetId?: string;
  imageUrl: string;
  mimeType?: string;
  width?: number;
  height?: number;
  aspectRatio?: number;
  submissionId?: string;
  submissionStatus?: "local_only" | "pending" | "published" | "rejected";
  pinnedAt?: string;
  lastClickedAt?: string;
  lastUsedAt?: string;
  clickCount?: number;
  useCount?: number;
  createdAt: string;
  updatedAt: string;
  sourceConversationId?: string;
  sourceTurnId?: string;
  sourceImageId?: string;
};

export type UserGalleryWaterfallAsset = {
  assetId: string;
  kind: string;
  url: string;
  fileId?: string;
  mimeType?: string;
  width?: number;
  height?: number;
  sizeBytes?: number;
  createdAt: string;
};

const galleryPromptStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "gallery_prompts",
});

const USER_PROMPTS_KEY_PREFIX = "user_prompts";
const USER_WATERFALL_ITEMS_KEY_PREFIX = "user_waterfall_items";
const PROMPT_STATS_KEY_PREFIX = "prompt_stats";
const DEFAULT_SCOPE = "__anonymous__";
const HASHED_SCOPE_PREFIX = "sha256:";
const galleryScopeMigrations = new Set<string>();

function normalizeScope(scope: string | null | undefined) {
  return String(scope || "").trim() || DEFAULT_SCOPE;
}

export async function buildGalleryStorageScope(scope: string | null | undefined) {
  const normalized = normalizeScope(scope);
  if (normalized === DEFAULT_SCOPE || normalized.startsWith(HASHED_SCOPE_PREFIX)) {
    return normalized;
  }
  if (typeof crypto === "undefined" || !crypto.subtle) {
    return `${HASHED_SCOPE_PREFIX}${promptKey(normalized)}`;
  }
  const bytes = new TextEncoder().encode(normalized);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `${HASHED_SCOPE_PREFIX}${hash}`;
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

async function migrateLegacyGalleryScope(
  legacyScope: string | null | undefined,
  storageScope: string,
) {
  const normalizedLegacyScope = normalizeScope(legacyScope);
  if (normalizedLegacyScope === storageScope || galleryScopeMigrations.has(storageScope)) {
    return;
  }
  galleryScopeMigrations.add(storageScope);
  const migrations: Array<[string, string]> = [
    [userPromptsKey(normalizedLegacyScope), userPromptsKey(storageScope)],
    [userWaterfallItemsKey(normalizedLegacyScope), userWaterfallItemsKey(storageScope)],
    [promptStatsKey(normalizedLegacyScope), promptStatsKey(storageScope)],
  ];
  for (const [legacyKey, storageKey] of migrations) {
    const current = await galleryPromptStorage.getItem<unknown>(storageKey);
    if (current !== null && current !== undefined) {
      continue;
    }
    const legacyValue = await galleryPromptStorage.getItem<unknown>(legacyKey);
    if (legacyValue !== null && legacyValue !== undefined) {
      await galleryPromptStorage.setItem(storageKey, legacyValue);
    }
  }
}

export async function resolveGalleryStorageScope(scope: string | null | undefined) {
  const storageScope = await buildGalleryStorageScope(scope);
  await migrateLegacyGalleryScope(scope, storageScope);
  return storageScope;
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
  const createdAt = String(value?.createdAt || "").trim() || now;
  const normalizedAsset = normalizeUserWaterfallAsset(
    Array.isArray(value?.assets) ? value.assets[0] : undefined,
    {
      imageUrl,
      mimeType: value?.mimeType,
      width,
      height,
      createdAt,
    },
  );
  const assets = normalizedAsset ? [normalizedAsset] : [];
  return {
    id: String(value?.id || "").trim() || createWaterfallItemId(),
    prompt,
    promptPreview: buildPromptPreview(value?.promptPreview || prompt),
    assets,
    coverAssetId: String(value?.coverAssetId || normalizedAsset?.assetId || "").trim() || undefined,
    imageUrl,
    mimeType: String(value?.mimeType || "").trim() || undefined,
    width,
    height,
    aspectRatio,
    submissionId: String(value?.submissionId || "").trim() || undefined,
    submissionStatus: normalizeSubmissionStatus(value?.submissionStatus),
    pinnedAt: String(value?.pinnedAt || value?.createdAt || "").trim() || now,
    lastClickedAt: String(value?.lastClickedAt || "").trim() || undefined,
    lastUsedAt: String(value?.lastUsedAt || "").trim() || undefined,
    clickCount: Math.max(0, Number(value?.clickCount || 0)),
    useCount: Math.max(0, Number(value?.useCount || 0)),
    createdAt,
    updatedAt: String(value?.updatedAt || "").trim() || now,
    sourceConversationId:
      String(value?.sourceConversationId || "").trim() || undefined,
    sourceTurnId: String(value?.sourceTurnId || "").trim() || undefined,
    sourceImageId: String(value?.sourceImageId || "").trim() || undefined,
  };
}

function normalizeSubmissionStatus(value: unknown) {
  const normalized = String(value || "").trim();
  if (normalized === "pending" || normalized === "published" || normalized === "rejected") {
    return normalized;
  }
  return "local_only";
}

function normalizeUserWaterfallAsset(
  value: UserGalleryWaterfallAsset | undefined,
  fallback: {
    imageUrl: string;
    mimeType?: string;
    width?: number;
    height?: number;
    createdAt: string;
  },
): UserGalleryWaterfallAsset | null {
  const url = String(value?.url || fallback.imageUrl || "").trim();
  if (!url) {
    return null;
  }
  return {
    assetId: String(value?.assetId || "").trim() || `asset-${promptKey(url)}`,
    kind: String(value?.kind || "").trim() || "image",
    url,
    fileId: String(value?.fileId || "").trim() || undefined,
    mimeType: String(value?.mimeType || fallback.mimeType || "").trim() || undefined,
    width: Math.max(0, Number(value?.width || fallback.width || 0)) || undefined,
    height: Math.max(0, Number(value?.height || fallback.height || 0)) || undefined,
    sizeBytes: Math.max(0, Number(value?.sizeBytes || 0)) || undefined,
    createdAt: String(value?.createdAt || "").trim() || fallback.createdAt,
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
    .sort((a, b) =>
      (b.pinnedAt || b.createdAt).localeCompare(a.pinnedAt || a.createdAt),
    );
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
    pinnedAt: now,
    createdAt: now,
    updatedAt: now,
  });
  if (!nextItem) {
    throw new Error("图片为空，无法添加");
  }
  const nextItems = [
    nextItem,
    ...items.filter((item) => item.id !== nextItem.id),
  ].sort((a, b) =>
    (b.pinnedAt || b.createdAt).localeCompare(a.pinnedAt || a.createdAt),
  );
  await galleryPromptStorage.setItem(userWaterfallItemsKey(scope), nextItems);
  return nextItem;
}

export async function updateUserGalleryWaterfallItemSubmission(
  scope: string | null | undefined,
  itemId: string,
  submission: {
    submissionId?: string;
    submissionStatus?: UserGalleryWaterfallItem["submissionStatus"];
  },
) {
  const normalizedId = String(itemId || "").trim();
  if (!normalizedId) {
    return null;
  }
  const items = await listUserGalleryWaterfallItems(scope);
  let updatedItem: UserGalleryWaterfallItem | null = null;
  const nextItems = items.map((item) => {
    if (item.id !== normalizedId) {
      return item;
    }
    updatedItem = {
      ...item,
      submissionId: String(submission.submissionId || item.submissionId || "").trim() || undefined,
      submissionStatus: normalizeSubmissionStatus(submission.submissionStatus),
      updatedAt: new Date().toISOString(),
    };
    return updatedItem;
  });
  await galleryPromptStorage.setItem(userWaterfallItemsKey(scope), nextItems);
  return updatedItem;
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
