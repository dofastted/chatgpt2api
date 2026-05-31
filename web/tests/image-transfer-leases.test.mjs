import assert from "node:assert/strict";
import test from "node:test";

import {
  acquireImageTransferLease,
  buildImageTransferAuthScope,
  reconcileImageTransferLeaseRecords,
} from "../src/lib/image-transfer-leases.ts";

function createLocalStorageMock() {
  const entries = new Map();
  return {
    getItem(key) {
      return entries.get(key) ?? null;
    },
    setItem(key, value) {
      entries.set(key, String(value));
    },
    removeItem(key) {
      entries.delete(key);
    },
  };
}

test("image transfer leases enforce three active records per auth scope", () => {
  const result = reconcileImageTransferLeaseRecords([], {
    scope: "sha256:user-a",
    ownerId: "owner-a",
    now: 1000,
    maxActiveLeases: 3,
    leaseTimeoutMs: 8000,
    targets: [
      { requestId: "queue-1" },
      { requestId: "queue-2" },
      { requestId: "queue-3" },
      { requestId: "queue-4" },
    ],
  });

  assert.deepEqual(result.ownedRequestIds, ["queue-1", "queue-2", "queue-3"]);
  assert.deepEqual(result.acquiredRequestIds, [
    "queue-1",
    "queue-2",
    "queue-3",
  ]);
  assert.deepEqual(result.skippedRequestIds, ["queue-4"]);
});

test("image transfer leases preserve existing owned records during single acquire", () => {
  const firstResult = reconcileImageTransferLeaseRecords([], {
    scope: "sha256:user-a",
    ownerId: "owner-a",
    now: 1000,
    maxActiveLeases: 3,
    leaseTimeoutMs: 8000,
    targets: [
      { requestId: "queue-1" },
      { requestId: "queue-2" },
      { requestId: "queue-3" },
    ],
  });
  const secondResult = reconcileImageTransferLeaseRecords(firstResult.records, {
    scope: "sha256:user-a",
    ownerId: "owner-a",
    now: 2000,
    maxActiveLeases: 3,
    leaseTimeoutMs: 8000,
    pruneOwnedMissingTargets: false,
    targets: [{ requestId: "queue-4" }],
  });

  assert.deepEqual(secondResult.ownedRequestIds, [
    "queue-1",
    "queue-2",
    "queue-3",
  ]);
  assert.deepEqual(secondResult.acquiredRequestIds, []);
  assert.deepEqual(secondResult.skippedRequestIds, ["queue-4"]);
});

test("acquiring a fourth transfer does not evict existing owned leases", () => {
  const previousWindow = globalThis.window;
  globalThis.window = { localStorage: createLocalStorageMock() };
  try {
    const firstResult = acquireImageTransferLease({
      scope: "sha256:user-a",
      ownerId: "owner-a",
      target: { requestId: "queue-1" },
    });
    const secondResult = acquireImageTransferLease({
      scope: "sha256:user-a",
      ownerId: "owner-a",
      target: { requestId: "queue-2" },
    });
    const thirdResult = acquireImageTransferLease({
      scope: "sha256:user-a",
      ownerId: "owner-a",
      target: { requestId: "queue-3" },
    });
    const fourthResult = acquireImageTransferLease({
      scope: "sha256:user-a",
      ownerId: "owner-a",
      target: { requestId: "queue-4" },
    });

    assert.deepEqual(firstResult.ownedRequestIds, ["queue-1"]);
    assert.deepEqual(secondResult.ownedRequestIds, ["queue-1", "queue-2"]);
    assert.deepEqual(thirdResult.ownedRequestIds, [
      "queue-1",
      "queue-2",
      "queue-3",
    ]);
    assert.deepEqual(fourthResult.ownedRequestIds, [
      "queue-1",
      "queue-2",
      "queue-3",
    ]);
    assert.deepEqual(fourthResult.acquiredRequestIds, []);
    assert.deepEqual(fourthResult.skippedRequestIds, ["queue-4"]);
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
});

test("image transfer leases adopt a stale owner after timeout", () => {
  const result = reconcileImageTransferLeaseRecords(
    [
      {
        requestId: "queue-1",
        ownerId: "owner-a",
        scope: "sha256:user-a",
        heartbeatAt: 1000,
        expiresAt: 2000,
      },
    ],
    {
      scope: "sha256:user-a",
      ownerId: "owner-b",
      now: 3000,
      leaseTimeoutMs: 8000,
      targets: [{ requestId: "queue-1" }],
    },
  );

  assert.deepEqual(result.ownedRequestIds, ["queue-1"]);
  assert.equal(result.records[0]?.ownerId, "owner-b");
});

test("image transfer auth scope does not expose the raw auth key", async () => {
  const rawScope = "Bearer sk-test-secret";
  const scope = await buildImageTransferAuthScope(rawScope);

  assert.match(scope, /^sha256:/);
  assert.equal(scope.includes(rawScope), false);
});
