"use client";

export const IMAGE_TRANSFER_MAX_ACTIVE_LEASES = 3;
export const IMAGE_TRANSFER_HEARTBEAT_MS = 2000;
export const IMAGE_TRANSFER_LEASE_TIMEOUT_MS = 8000;

const STORAGE_KEY = "image_transfer_leases:v1";
const EVENT_KEY = "image_transfer_leases_event:v1";
const CHANNEL_NAME = "chatgpt2api:image-transfer-leases";
const HASHED_SCOPE_PREFIX = "sha256:";

export type ImageTransferTarget = {
  requestId: string;
  conversationId?: string;
  turnId?: string;
};

export type ImageTransferLeaseRecord = ImageTransferTarget & {
  ownerId: string;
  scope: string;
  heartbeatAt: number;
  expiresAt: number;
};

export type ImageTransferLeaseReconcileResult = {
  records: ImageTransferLeaseRecord[];
  ownedRequestIds: string[];
  acquiredRequestIds: string[];
  skippedRequestIds: string[];
};

type ImageTransferLeaseStorage = {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
  removeItem: (key: string) => void;
};

function normalizeRequestId(value: string | null | undefined) {
  return String(value || "").trim();
}

function normalizeScope(value: string | null | undefined) {
  return String(value || "").trim() || "__anonymous__";
}

function fallbackHash(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export async function buildImageTransferAuthScope(
  scope: string | null | undefined,
) {
  const normalized = normalizeScope(scope);
  if (
    normalized === "__anonymous__" ||
    normalized.startsWith(HASHED_SCOPE_PREFIX)
  ) {
    return normalized;
  }
  if (typeof crypto === "undefined" || !crypto.subtle) {
    return `${HASHED_SCOPE_PREFIX}${fallbackHash(normalized)}`;
  }
  const bytes = new TextEncoder().encode(normalized);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `${HASHED_SCOPE_PREFIX}${hash}`;
}

export function createImageTransferOwnerId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `image-window-${crypto.randomUUID()}`;
  }
  return `image-window-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeTarget(
  target: ImageTransferTarget,
): ImageTransferTarget | null {
  const requestId = normalizeRequestId(target.requestId);
  if (!requestId) {
    return null;
  }
  return {
    requestId,
    conversationId: normalizeRequestId(target.conversationId),
    turnId: normalizeRequestId(target.turnId),
  };
}

function normalizeRecord(
  value: ImageTransferLeaseRecord,
): ImageTransferLeaseRecord | null {
  const target = normalizeTarget(value);
  const ownerId = normalizeRequestId(value?.ownerId);
  const scope = normalizeScope(value?.scope);
  if (!target || !ownerId || !scope) {
    return null;
  }
  return {
    ...target,
    ownerId,
    scope,
    heartbeatAt: Math.max(0, Number(value?.heartbeatAt || 0)),
    expiresAt: Math.max(0, Number(value?.expiresAt || 0)),
  };
}

export function reconcileImageTransferLeaseRecords(
  records: ImageTransferLeaseRecord[],
  options: {
    scope: string;
    ownerId: string;
    targets: ImageTransferTarget[];
    now?: number;
    maxActiveLeases?: number;
    leaseTimeoutMs?: number;
    pruneOwnedMissingTargets?: boolean;
  },
): ImageTransferLeaseReconcileResult {
  const scope = normalizeScope(options.scope);
  const ownerId = normalizeRequestId(options.ownerId);
  const now = Math.max(0, Number(options.now ?? Date.now()));
  const maxActiveLeases = Math.max(
    1,
    Number(options.maxActiveLeases || IMAGE_TRANSFER_MAX_ACTIVE_LEASES),
  );
  const leaseTimeoutMs = Math.max(
    1000,
    Number(options.leaseTimeoutMs || IMAGE_TRANSFER_LEASE_TIMEOUT_MS),
  );
  const shouldPruneOwnedMissingTargets =
    options.pruneOwnedMissingTargets !== false;
  const targets = options.targets
    .map(normalizeTarget)
    .filter((target): target is ImageTransferTarget => Boolean(target));
  const targetByRequestId = new Map(
    targets.map((target) => [target.requestId, target]),
  );
  const recordsByRequestId = new Map<string, ImageTransferLeaseRecord>();

  for (const rawRecord of records) {
    const record = normalizeRecord(rawRecord);
    if (!record || record.expiresAt <= now) {
      continue;
    }
    if (
      shouldPruneOwnedMissingTargets &&
      record.scope === scope &&
      record.ownerId === ownerId &&
      !targetByRequestId.has(record.requestId)
    ) {
      continue;
    }
    recordsByRequestId.set(record.requestId, record);
  }

  const acquiredRequestIds: string[] = [];
  const skippedRequestIds: string[] = [];

  for (const target of targets) {
    const existing = recordsByRequestId.get(target.requestId);
    if (existing && existing.scope === scope && existing.ownerId === ownerId) {
      recordsByRequestId.set(target.requestId, {
        ...existing,
        ...target,
        heartbeatAt: now,
        expiresAt: now + leaseTimeoutMs,
      });
      continue;
    }
    if (existing && existing.scope === scope && existing.ownerId !== ownerId) {
      skippedRequestIds.push(target.requestId);
      continue;
    }

    const activeForScope = Array.from(recordsByRequestId.values()).filter(
      (record) => record.scope === scope,
    ).length;
    if (activeForScope >= maxActiveLeases) {
      skippedRequestIds.push(target.requestId);
      continue;
    }

    recordsByRequestId.set(target.requestId, {
      ...target,
      ownerId,
      scope,
      heartbeatAt: now,
      expiresAt: now + leaseTimeoutMs,
    });
    acquiredRequestIds.push(target.requestId);
  }

  const nextRecords = Array.from(recordsByRequestId.values()).sort((a, b) =>
    a.requestId.localeCompare(b.requestId),
  );
  const ownedRequestIds = nextRecords
    .filter((record) => record.scope === scope && record.ownerId === ownerId)
    .map((record) => record.requestId);

  return {
    records: nextRecords,
    ownedRequestIds,
    acquiredRequestIds,
    skippedRequestIds,
  };
}

function getStorage(): ImageTransferLeaseStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readRecords(
  storage: ImageTransferLeaseStorage,
): ImageTransferLeaseRecord[] {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeRecords(
  storage: ImageTransferLeaseStorage,
  records: ImageTransferLeaseRecord[],
) {
  if (records.length === 0) {
    storage.removeItem(STORAGE_KEY);
    return;
  }
  storage.setItem(STORAGE_KEY, JSON.stringify(records));
}

function publishLeaseChange() {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(EVENT_KEY, String(Date.now()));
  } catch {
    // BroadcastChannel below is enough when localStorage event writes are blocked.
  }
  try {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    channel.postMessage({ type: "changed" });
    channel.close();
  } catch {
    return;
  }
}

export function reconcileImageTransferLeases(options: {
  scope: string;
  ownerId: string;
  targets: ImageTransferTarget[];
  pruneOwnedMissingTargets?: boolean;
}) {
  const storage = getStorage();
  if (!storage) {
    return {
      ownedRequestIds: options.targets
        .map((target) => normalizeRequestId(target.requestId))
        .filter(Boolean),
    };
  }
  const result = reconcileImageTransferLeaseRecords(readRecords(storage), {
    ...options,
    pruneOwnedMissingTargets: options.pruneOwnedMissingTargets,
  });
  writeRecords(storage, result.records);
  if (
    result.acquiredRequestIds.length > 0 ||
    result.skippedRequestIds.length > 0
  ) {
    publishLeaseChange();
  }
  return result;
}

export function acquireImageTransferLease(options: {
  scope: string;
  ownerId: string;
  target: ImageTransferTarget;
}) {
  return reconcileImageTransferLeases({
    scope: options.scope,
    ownerId: options.ownerId,
    targets: [options.target],
    pruneOwnedMissingTargets: false,
  });
}

export function releaseImageTransferLeases(options: {
  scope: string;
  ownerId: string;
  requestIds?: string[];
}) {
  const storage = getStorage();
  if (!storage) {
    return { ownedRequestIds: [] };
  }
  const scope = normalizeScope(options.scope);
  const ownerId = normalizeRequestId(options.ownerId);
  const requestIds = new Set(
    (options.requestIds || []).map(normalizeRequestId).filter(Boolean),
  );
  const nextRecords = readRecords(storage).filter((record) => {
    const normalized = normalizeRecord(record);
    if (!normalized) {
      return false;
    }
    const isOwned =
      normalized.scope === scope && normalized.ownerId === ownerId;
    if (!isOwned) {
      return true;
    }
    return requestIds.size > 0 && !requestIds.has(normalized.requestId);
  });
  writeRecords(storage, nextRecords);
  publishLeaseChange();
  return {
    ownedRequestIds: nextRecords
      .filter((record) => record.scope === scope && record.ownerId === ownerId)
      .map((record) => record.requestId),
  };
}

export function subscribeImageTransferLeaseChanges(callback: () => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = () => callback();
  } catch {
    channel = null;
  }

  const handleStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === EVENT_KEY) {
      callback();
    }
  };
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener("storage", handleStorage);
    channel?.close();
  };
}
