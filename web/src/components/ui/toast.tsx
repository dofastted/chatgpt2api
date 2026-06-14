"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

type ToastType = "error" | "success" | "message";

type ToastItem = {
  id: number;
  message: ReactNode;
  type: ToastType;
};

type ToastListener = (items: ToastItem[]) => void;

const TOAST_DURATION_MS = 3600;
let nextToastId = 1;
let currentToasts: ToastItem[] = [];
const listeners = new Set<ToastListener>();

function notify() {
  const snapshot = [...currentToasts];
  for (const listener of listeners) {
    listener(snapshot);
  }
}

function dismissToast(id: number) {
  const nextToasts = currentToasts.filter((item) => item.id !== id);
  if (nextToasts.length === currentToasts.length) {
    return;
  }
  currentToasts = nextToasts;
  notify();
}

function pushToast(type: ToastType, message: ReactNode) {
  const id = nextToastId;
  nextToastId += 1;
  currentToasts = [...currentToasts.slice(-3), { id, message, type }];
  notify();
  window.setTimeout(() => dismissToast(id), TOAST_DURATION_MS);
  return id;
}

export const toast = {
  error(message: ReactNode) {
    return pushToast("error", message);
  },
  message(message: ReactNode) {
    return pushToast("message", message);
  },
  success(message: ReactNode) {
    return pushToast("success", message);
  },
};

export function Toaster() {
  const [items, setItems] = useState<ToastItem[]>(() => currentToasts);

  useEffect(() => {
    listeners.add(setItems);
    return () => {
      listeners.delete(setItems);
    };
  }, []);

  if (items.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="通知"
      aria-live="polite"
      aria-relevant="additions text"
      className="fixed top-4 left-1/2 z-[100] flex w-[min(92vw,420px)] -translate-x-1/2 flex-col gap-2"
    >
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => dismissToast(item.id)}
          className={resolveToastClassName(item.type)}
        >
          {item.message}
        </button>
      ))}
    </section>
  );
}

function resolveToastClassName(type: ToastType) {
  const base =
    "rounded-xl border px-4 py-3 text-left text-sm leading-6 shadow-lg backdrop-blur transition";
  if (type === "error") {
    return `${base} border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-900/70 dark:bg-rose-950/90 dark:text-rose-100`;
  }
  if (type === "success") {
    return `${base} border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-900/70 dark:bg-emerald-950/90 dark:text-emerald-100`;
  }
  return `${base} border-border bg-card text-foreground`;
}
