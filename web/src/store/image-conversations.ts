"use client";

import localforage from "localforage";

import { detectImageMimeType } from "@/lib/image-data";
import {
  deleteImageConversationFromServer,
  fetchImageConversation,
  fetchImageConversations,
  saveImageConversationToServer,
  type ImageConversationPayload,
  type ImageModel,
} from "@/lib/api";
import {
  DEFAULT_IMAGE_GENERATION_PREFERENCE,
  normalizeImageGenerationPreference,
  type ImageGenerationPreference,
} from "@/lib/image-size";

export type StoredImage = {
  id: string;
  status?: "loading" | "success" | "error";
  b64_json?: string;
  mimeType?: string;
  error?: string;
};

export type StoredInputImage = {
  id: string;
  fileId?: string;
  fileName?: string;
  dataUrl: string;
  mimeType?: string;
  sizeBytes?: number;
  clientConversationId?: string;
};

export type ImageConversationStatus = "draft" | "queued" | "assigning_account" | "running" | "success" | "error";

export type ImageConversationTurn = {
  id: string;
  prompt: string;
  model: ImageModel;
  count: number;
  size: string;
  copiedText?: string;
  inputImage?: StoredInputImage | null;
  images: StoredImage[];
  createdAt: string;
  status: ImageConversationStatus;
  error?: string;
  queueRequestId?: string;
  requestStartedAt?: string;
  requestFinishedAt?: string;
  lastError?: string;
  responseId?: string;
};

export type ImageConversation = {
  id: string;
  clientConversationId: string;
  title: string;
  createdAt: string;
  turns: ImageConversationTurn[];
  prompt?: string;
  model?: ImageModel;
  count?: number;
  size?: string;
  copiedText?: string;
  inputImage?: StoredInputImage | null;
  images?: StoredImage[];
  status?: ImageConversationStatus;
  error?: string;
  queueRequestId?: string;
  requestStartedAt?: string;
  requestFinishedAt?: string;
  lastError?: string;
  responseId?: string;
  isSummary?: boolean;
  turnCount?: number;
};

const imageConversationStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "image_conversations",
});

const IMAGE_CONVERSATIONS_KEY_PREFIX = "items";
const IMAGE_PREFERENCE_KEY_PREFIX = "generation_preference";
const IMAGE_SERVER_MIGRATION_KEY_PREFIX = "server_migrated";
const IMAGE_CONVERSATIONS_DEFAULT_SCOPE = "__anonymous__";
export const IMAGE_CONVERSATION_SUMMARY_LIMIT = 10;
const conversationWriteQueues = new Map<string, Promise<void>>();
const VALID_IMAGE_MODELS = new Set<ImageModel>([
  "gpt-image-2",
  "gpt-image-2-2K",
  "gpt-image-2-4K",
]);

function normalizeImageModel(value: unknown): ImageModel {
  const normalized = String(value || "").trim() as ImageModel;
  return VALID_IMAGE_MODELS.has(normalized) ? normalized : "gpt-image-2";
}

function normalizeConversationScope(scope: string): string {
  const normalized = String(scope || "").trim();
  return normalized || IMAGE_CONVERSATIONS_DEFAULT_SCOPE;
}

function buildConversationStorageKey(scope: string): string {
  return `${IMAGE_CONVERSATIONS_KEY_PREFIX}:${normalizeConversationScope(scope)}`;
}

function buildPreferenceStorageKey(scope: string): string {
  return `${IMAGE_PREFERENCE_KEY_PREFIX}:${normalizeConversationScope(scope)}`;
}

function buildServerMigrationKey(scope: string): string {
  return `${IMAGE_SERVER_MIGRATION_KEY_PREFIX}:${normalizeConversationScope(scope)}`;
}

async function readLocalConversations(
  scope: string,
  options: { limit?: number } = {},
): Promise<ImageConversation[]> {
  const localItems =
    (await imageConversationStorage.getItem<ImageConversation[]>(buildConversationStorageKey(scope))) || [];
  const sortedItems = [...localItems].sort((a, b) =>
    String(b?.createdAt || "").localeCompare(String(a?.createdAt || "")),
  );
  const limit = Number(options.limit || 0);
  const selectedItems = limit > 0 ? sortedItems.slice(0, limit) : sortedItems;
  return selectedItems.map(normalizeConversation);
}

function sortConversationsByCreatedAt(items: ImageConversation[]): ImageConversation[] {
  return [...items].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function mergeConversationLists(
  primaryItems: ImageConversation[],
  secondaryItems: ImageConversation[],
): ImageConversation[] {
  const merged = new Map<string, ImageConversation>();
  for (const item of secondaryItems) {
    merged.set(item.id, item);
  }
  for (const item of primaryItems) {
    merged.set(item.id, item);
  }
  return sortConversationsByCreatedAt(Array.from(merged.values()));
}

async function migrateLocalConversationsIfNeeded(
  scope: string,
  normalizedLocalItems: ImageConversation[],
): Promise<boolean> {
  const migrated = Boolean(await imageConversationStorage.getItem<boolean>(buildServerMigrationKey(scope)));
  if (!migrated && normalizedLocalItems.length > 0) {
    for (const item of normalizedLocalItems) {
      await saveImageConversationToServer(item as unknown as ImageConversationPayload);
    }
    await imageConversationStorage.setItem(buildServerMigrationKey(scope), true);
    return true;
  }
  return migrated;
}

function enqueueConversationWrite<T>(scope: string, operation: () => Promise<T>): Promise<T> {
  const normalizedScope = normalizeConversationScope(scope);
  const previous = conversationWriteQueues.get(normalizedScope) || Promise.resolve();
  const next = previous.catch(() => undefined).then(operation);
  const queued = next.then(
    () => undefined,
    () => undefined,
  );
  conversationWriteQueues.set(
    normalizedScope,
    queued,
  );
  return next.finally(() => {
    if (conversationWriteQueues.get(normalizedScope) === queued) {
      conversationWriteQueues.delete(normalizedScope);
    }
  });
}

function normalizeStoredImage(image: StoredImage): StoredImage {
  const normalizedMimeType = image.b64_json
    ? String(image.mimeType || "").trim() || detectImageMimeType(image.b64_json)
    : undefined;
  if (image.status === "loading" || image.status === "error" || image.status === "success") {
    return {
      ...image,
      mimeType: normalizedMimeType,
    };
  }
  return {
    ...image,
    status: image.b64_json ? "success" : "loading",
    mimeType: normalizedMimeType,
  };
}

function normalizeStoredInputImage(inputImage: StoredInputImage | null | undefined): StoredInputImage | undefined {
  if (!inputImage || !String(inputImage.dataUrl || "").trim()) {
    return undefined;
  }
  const dataUrl = String(inputImage.dataUrl || "").trim();
  const mimePrefix = dataUrl.startsWith("data:") ? dataUrl.slice(5).split(";", 1)[0].trim() : "";
  return {
    ...inputImage,
    fileId: String(inputImage.fileId || "").trim() || undefined,
    clientConversationId: String(inputImage.clientConversationId || "").trim() || undefined,
    dataUrl,
    mimeType: String(inputImage.mimeType || "").trim() || mimePrefix || "image/png",
    fileName: String(inputImage.fileName || "").trim() || undefined,
    sizeBytes: inputImage.sizeBytes ? Math.max(0, Number(inputImage.sizeBytes || 0)) : undefined,
  };
}

function normalizeTurn(turn: ImageConversationTurn, fallbackId: string): ImageConversationTurn {
  const normalizedStatus =
    turn.status === "success" ||
    turn.status === "error" ||
    turn.status === "draft" ||
    turn.status === "queued" ||
    turn.status === "assigning_account" ||
    turn.status === "running"
      ? turn.status
      : "error";
  return {
    ...turn,
    id: String(turn.id || fallbackId || "").trim() || `turn-${Date.now()}`,
    prompt: String(turn.prompt || "").trim(),
    model: normalizeImageModel(turn.model),
    count: Math.max(1, Number(turn.count || 1)),
    size: String(turn.size || "auto").trim() || "auto",
    copiedText: String(turn.copiedText || "").trim() || undefined,
    inputImage: normalizeStoredInputImage(turn.inputImage),
    images: (turn.images || []).map(normalizeStoredImage),
    status: normalizedStatus,
    queueRequestId: String(turn.queueRequestId || "").trim() || undefined,
    requestStartedAt: String(turn.requestStartedAt || "").trim() || undefined,
    requestFinishedAt: String(turn.requestFinishedAt || "").trim() || undefined,
    lastError: String(turn.lastError || turn.error || "").trim() || undefined,
    error: String(turn.error || "").trim() || undefined,
    responseId: String(turn.responseId || "").trim() || undefined,
  };
}

function legacyConversationToTurn(conversation: ImageConversation): ImageConversationTurn {
  return normalizeTurn(
    {
      id: `${conversation.id}-turn-1`,
      prompt: String(conversation.prompt || "").trim(),
      model: normalizeImageModel(conversation.model),
      count: Math.max(1, Number(conversation.count || 1)),
      size: String(conversation.size || "auto").trim() || "auto",
      copiedText: conversation.copiedText,
      inputImage: conversation.inputImage,
      images: conversation.images || [],
      createdAt: conversation.createdAt,
      status: conversation.status || "draft",
      error: conversation.error,
      queueRequestId: conversation.queueRequestId,
      requestStartedAt: conversation.requestStartedAt,
      requestFinishedAt: conversation.requestFinishedAt,
      lastError: conversation.lastError,
      responseId: conversation.responseId,
    },
    `${conversation.id}-turn-1`,
  );
}

function normalizeConversation(conversation: ImageConversation): ImageConversation {
  const clientConversationId =
    String(conversation.clientConversationId || conversation.id || "").trim() ||
    String(conversation.id || "").trim();
  const turns = Array.isArray(conversation.turns) && conversation.turns.length > 0
    ? conversation.turns.map((turn, index) => normalizeTurn(turn, `${conversation.id}-turn-${index + 1}`))
    : [legacyConversationToTurn(conversation)];
  const latestTurn = turns[turns.length - 1];
  return {
    ...conversation,
    clientConversationId,
    turns,
    prompt: latestTurn.prompt,
    model: latestTurn.model,
    count: latestTurn.count,
    size: latestTurn.size,
    copiedText: latestTurn.copiedText,
    inputImage: latestTurn.inputImage,
    images: latestTurn.images,
    status: latestTurn.status,
    queueRequestId: latestTurn.queueRequestId,
    requestStartedAt: latestTurn.requestStartedAt,
    requestFinishedAt: latestTurn.requestFinishedAt,
    lastError: latestTurn.lastError,
    error: latestTurn.error,
    responseId: latestTurn.responseId,
    isSummary: Boolean(conversation.isSummary) || undefined,
    turnCount: Math.max(Number(conversation.turnCount || turns.length) || turns.length, turns.length),
  };
}

export async function listImageConversations(scope: string): Promise<ImageConversation[]> {
  const normalizedLocalItems = await readLocalConversations(scope);
  try {
    const migrated = await migrateLocalConversationsIfNeeded(scope, normalizedLocalItems);
    const response = await fetchImageConversations();
    const serverItems = (response.items || [])
      .map((item) => normalizeConversation(item as unknown as ImageConversation))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    if (serverItems.length > 0 || migrated) {
      await imageConversationStorage.setItem(buildConversationStorageKey(scope), serverItems);
      return serverItems;
    }
  } catch {
    return normalizedLocalItems;
  }
  return normalizedLocalItems;
}

export async function listCachedImageConversationSummaries(scope: string): Promise<ImageConversation[]> {
  return readLocalConversations(scope, {
    limit: IMAGE_CONVERSATION_SUMMARY_LIMIT,
  });
}

export async function listImageConversationSummaries(scope: string): Promise<ImageConversation[]> {
  const localItems = await readLocalConversations(scope, {
    limit: IMAGE_CONVERSATION_SUMMARY_LIMIT,
  });
  try {
    const response = await fetchImageConversations({
      summary: true,
      limit: IMAGE_CONVERSATION_SUMMARY_LIMIT,
      offset: 0,
    });
    const serverItems = (response.items || [])
      .map((item) => normalizeConversation(item as unknown as ImageConversation))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    if (serverItems.length > 0 || localItems.length > 0) {
      return mergeConversationLists(serverItems, localItems).slice(0, IMAGE_CONVERSATION_SUMMARY_LIMIT);
    }
  } catch {
    return localItems;
  }
  return [];
}

export async function listMoreImageConversationSummaries(
  scope: string,
  offset: number,
  limit = IMAGE_CONVERSATION_SUMMARY_LIMIT,
): Promise<ImageConversation[]> {
  const normalizedOffset = Math.max(0, Number(offset || 0));
  const normalizedLimit = Math.max(1, Math.min(100, Number(limit || IMAGE_CONVERSATION_SUMMARY_LIMIT)));
  try {
    const response = await fetchImageConversations({
      summary: true,
      limit: normalizedLimit,
      offset: normalizedOffset,
    });
    const serverItems = (response.items || [])
      .map((item) => normalizeConversation(item as unknown as ImageConversation))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    if (serverItems.length > 0) {
      return serverItems;
    }
    const localItems = await readLocalConversations(scope);
    return localItems.slice(normalizedOffset, normalizedOffset + normalizedLimit);
  } catch {
    const localItems = await readLocalConversations(scope);
    return localItems.slice(normalizedOffset, normalizedOffset + normalizedLimit);
  }
}

export async function getImageConversationDetail(scope: string, id: string): Promise<ImageConversation> {
  try {
    const response = await fetchImageConversation(id);
    const item = normalizeConversation(response.item as unknown as ImageConversation);
    const localItems = await readLocalConversations(scope);
    const nextItems = [item, ...localItems.filter((conversation) => conversation.id !== item.id)].sort((a, b) =>
      b.createdAt.localeCompare(a.createdAt),
    );
    await imageConversationStorage.setItem(buildConversationStorageKey(scope), nextItems);
    return item;
  } catch (error) {
    const fallback = (await readLocalConversations(scope)).find((item) => item.id === id);
    if (fallback) {
      return fallback;
    }
    throw error;
  }
}

export async function saveImageConversation(scope: string, conversation: ImageConversation): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const items = await readLocalConversations(scope);
    const nextItems = [normalizeConversation(conversation), ...items.filter((item) => item.id !== conversation.id)];
    nextItems.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    await imageConversationStorage.setItem(buildConversationStorageKey(scope), nextItems);
    try {
      await saveImageConversationToServer(normalizeConversation(conversation) as unknown as ImageConversationPayload);
    } catch {
      return;
    }
  });
}

export async function replaceImageConversations(scope: string, conversations: ImageConversation[]): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const nextItems = conversations.map(normalizeConversation);
    nextItems.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    await imageConversationStorage.setItem(buildConversationStorageKey(scope), nextItems);
    try {
      for (const item of nextItems) {
        await saveImageConversationToServer(item as unknown as ImageConversationPayload);
      }
    } catch {
      return;
    }
  });
}

export async function deleteImageConversation(scope: string, id: string): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const items = await readLocalConversations(scope);
    await imageConversationStorage.setItem(
      buildConversationStorageKey(scope),
      items.filter((item) => item.id !== id),
    );
    try {
      await deleteImageConversationFromServer(id);
    } catch {
      return;
    }
  });
}

export async function clearImageConversations(scope: string): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const items = await listImageConversations(scope);
    await imageConversationStorage.removeItem(buildConversationStorageKey(scope));
    try {
      for (const item of items) {
        await deleteImageConversationFromServer(item.id);
      }
    } catch {
      return;
    }
  });
}

export async function getImageGenerationPreference(
  scope: string,
): Promise<ImageGenerationPreference> {
  const stored = await imageConversationStorage.getItem<Partial<ImageGenerationPreference>>(
    buildPreferenceStorageKey(scope),
  );
  return normalizeImageGenerationPreference(stored || DEFAULT_IMAGE_GENERATION_PREFERENCE);
}

export async function saveImageGenerationPreference(
  scope: string,
  preference: ImageGenerationPreference,
): Promise<void> {
  await imageConversationStorage.setItem(
    buildPreferenceStorageKey(scope),
    normalizeImageGenerationPreference(preference),
  );
}
