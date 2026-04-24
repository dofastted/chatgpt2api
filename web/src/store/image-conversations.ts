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

export type ImageConversation = {
  id: string;
  clientConversationId: string;
  title: string;
  prompt: string;
  model: ImageModel;
  count: number;
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

function normalizeConversation(conversation: ImageConversation): ImageConversation {
  const clientConversationId =
    String(conversation.clientConversationId || conversation.id || "").trim() ||
    String(conversation.id || "").trim();
  const normalizedStatus =
    conversation.status === "success" ||
    conversation.status === "error" ||
    conversation.status === "draft" ||
    conversation.status === "queued" ||
    conversation.status === "assigning_account" ||
    conversation.status === "running"
      ? conversation.status
      : "error";
  return {
    ...conversation,
    clientConversationId,
    copiedText: String(conversation.copiedText || "").trim() || undefined,
    inputImage: normalizeStoredInputImage(conversation.inputImage),
    images: (conversation.images || []).map(normalizeStoredImage),
    status: normalizedStatus,
    queueRequestId: String(conversation.queueRequestId || "").trim() || undefined,
    requestStartedAt: String(conversation.requestStartedAt || "").trim() || undefined,
    requestFinishedAt: String(conversation.requestFinishedAt || "").trim() || undefined,
    lastError: String(conversation.lastError || conversation.error || "").trim() || undefined,
    error: String(conversation.error || "").trim() || undefined,
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
