"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { fetchAuthSession } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    const redirectByRole = async () => {
      try {
        const session = await fetchAuthSession({ redirectOnUnauthorized: false, retries: 1 });
        if (!cancelled) {
          router.replace(session.role === "admin" ? "/accounts" : "/image");
        }
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      }
    };

    void redirectByRole();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return null;
}
