"use client";

import localforage from "localforage";

import { detectImageMimeType } from "@/lib/image-data";
import type { ImageModel } from "@/lib/api";

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
};

const imageConversationStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "image_conversations",
});

const IMAGE_CONVERSATIONS_KEY_PREFIX = "items";
const IMAGE_CONVERSATIONS_DEFAULT_SCOPE = "__anonymous__";
const conversationWriteQueues = new Map<string, Promise<void>>();

function normalizeConversationScope(scope: string): string {
  const normalized = String(scope || "").trim();
  return normalized || IMAGE_CONVERSATIONS_DEFAULT_SCOPE;
}

function buildConversationStorageKey(scope: string): string {
  return `${IMAGE_CONVERSATIONS_KEY_PREFIX}:${normalizeConversationScope(scope)}`;
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
    model: (turn.model || "gpt-image-2") as ImageModel,
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
      model: (conversation.model || "gpt-image-2") as ImageModel,
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
  };
}

export async function listImageConversations(scope: string): Promise<ImageConversation[]> {
  const items =
    (await imageConversationStorage.getItem<ImageConversation[]>(buildConversationStorageKey(scope))) || [];
  return items.map(normalizeConversation).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function saveImageConversation(scope: string, conversation: ImageConversation): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const items = await listImageConversations(scope);
    const nextItems = [normalizeConversation(conversation), ...items.filter((item) => item.id !== conversation.id)];
    nextItems.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    await imageConversationStorage.setItem(buildConversationStorageKey(scope), nextItems);
  });
}

export async function replaceImageConversations(scope: string, conversations: ImageConversation[]): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const nextItems = conversations.map(normalizeConversation);
    nextItems.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    await imageConversationStorage.setItem(buildConversationStorageKey(scope), nextItems);
  });
}

export async function deleteImageConversation(scope: string, id: string): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    const items = await listImageConversations(scope);
    await imageConversationStorage.setItem(
      buildConversationStorageKey(scope),
      items.filter((item) => item.id !== id),
    );
  });
}

export async function clearImageConversations(scope: string): Promise<void> {
  await enqueueConversationWrite(scope, async () => {
    await imageConversationStorage.removeItem(buildConversationStorageKey(scope));
  });
}
