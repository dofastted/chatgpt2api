"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Gift,
  LoaderCircle,
  LogOut,
  Palette,
  Ticket,
  Upload,
} from "lucide-react";
import { toast } from "@/components/ui/toast";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import webConfig from "@/constants/common-env";
import { cleanJsonText, extractAccountsFromJson } from "@/lib/account-import";
import {
  createDonationAccounts,
  fetchAuthSession,
  redeemCode,
  type AuthRole,
  type AuthType,
} from "@/lib/api";
import { clearStoredAuthKey } from "@/store/auth";
import { cn } from "@/lib/utils";

const navItems: Array<{ href: string; label: string; roles?: AuthRole[] }> = [
  { href: "/image", label: "画图" },
  { href: "/gallery", label: "画廊" },
  { href: "/accounts", label: "号池管理", roles: ["admin"] },
];

type SessionState = {
  role: AuthRole | null;
  authType: AuthType | null;
  remainingQuota: number | null;
};

const redeemCodePurchaseLinks = [
  {
    href: "https://ldc.fkcodex.com/buy/4",
    quota: 20,
    label: "购买 20 额度兑换码",
  },
  {
    href: "https://ldc.fkcodex.com/buy/5",
    quota: 100,
    label: "购买 100 额度兑换码",
  },
] as const;

const THEME_STORAGE_KEY = "chatgpt2api-theme";

type ThemeMode = "light" | "dark" | "system";

const themeModeOptions: Array<{ label: string; value: ThemeMode }> = [
  { label: "跟随系统", value: "system" },
  { label: "白色", value: "light" },
  { label: "黑色", value: "dark" },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [sessionState, setSessionState] = useState<SessionState>({
    role: null,
    authType: null,
    remainingQuota: null,
  });
  const [centerOpen, setCenterOpen] = useState(false);
  const [isUploadingDonation, setIsUploadingDonation] = useState(false);
  const [isRedeemingCode, setIsRedeemingCode] = useState(false);
  const [redeemInput, setRedeemInput] = useState("");
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") {
      return "system";
    }
    const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (
      storedTheme === "light" ||
      storedTheme === "dark" ||
      storedTheme === "system"
    ) {
      return storedTheme;
    }
    return "system";
  });

  const syncSession = async () => {
    const session = await fetchAuthSession({
      redirectOnUnauthorized: false,
      retries: 1,
    });
    setSessionState({
      role: session.role,
      authType: session.auth_type ?? null,
      remainingQuota:
        session.remaining_quota === null ||
        session.remaining_quota === undefined
          ? null
          : Math.max(0, Number(session.remaining_quota || 0)),
    });
  };

  useEffect(() => {
    if (pathname === "/login") {
      return;
    }

    let cancelled = false;
    const loadSession = async () => {
      try {
        const session = await fetchAuthSession({
          redirectOnUnauthorized: false,
          retries: 1,
        });
        if (!cancelled) {
          setSessionState({
            role: session.role,
            authType: session.auth_type ?? null,
            remainingQuota:
              session.remaining_quota === null ||
              session.remaining_quota === undefined
                ? null
                : Math.max(0, Number(session.remaining_quota || 0)),
          });
        }
      } catch {
        if (!cancelled) {
          setSessionState({
            role: null,
            authType: null,
            remainingQuota: null,
          });
        }
      }
    };

    void loadSession();
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const resolvedTheme =
        themeMode === "system"
          ? mediaQuery.matches
            ? "dark"
            : "light"
          : themeMode;

      root.classList.toggle("dark", resolvedTheme === "dark");
      root.classList.toggle("light", resolvedTheme === "light");
      root.style.colorScheme = resolvedTheme;
    };

    applyTheme();
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);

    if (themeMode !== "system") {
      return;
    }

    const handleChange = () => {
      applyTheme();
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, [themeMode]);

  const handleLogout = async () => {
    await clearStoredAuthKey();
    router.replace("/login");
  };

  const handleDonationUpload = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setIsUploadingDonation(true);

    try {
      const importedAccounts: Array<{
        access_token: string;
        [key: string]: unknown;
      }> = [];
      const invalidFiles: string[] = [];
      const emptyFiles: string[] = [];
      let matchedFiles = 0;

      for (const file of files) {
        try {
          const text = cleanJsonText(await file.text());
          if (!text) {
            emptyFiles.push(file.name);
            continue;
          }

          const payload = JSON.parse(text);
          const fileAccounts = extractAccountsFromJson(payload);
          if (fileAccounts.length === 0) {
            emptyFiles.push(file.name);
            continue;
          }

          matchedFiles += 1;
          importedAccounts.push(...fileAccounts);
        } catch {
          invalidFiles.push(file.name);
        }
      }

      const indexedAccounts = new Map<
        string,
        { access_token: string; [key: string]: unknown }
      >();
      importedAccounts.forEach((item) => {
        const accessToken = String(item.access_token || "").trim();
        if (!accessToken) {
          return;
        }
        indexedAccounts.set(accessToken, {
          ...indexedAccounts.get(accessToken),
          ...item,
          access_token: accessToken,
        });
      });
      const accountsToImport = Array.from(indexedAccounts.values());
      if (accountsToImport.length === 0) {
        const errors: string[] = [];
        if (invalidFiles.length > 0) {
          errors.push(`${invalidFiles.length} 个文件不是有效 JSON`);
        }
        if (emptyFiles.length > 0) {
          errors.push(`${emptyFiles.length} 个文件没有可识别的 token 字段`);
        }
        toast.error(
          errors.length > 0
            ? `未提取到可用 Token，${errors.join("，")}`
            : "未提取到可用 Token",
        );
        return;
      }

      const data = await createDonationAccounts({ accounts: accountsToImport });
      const errorCount = data.errors?.length ?? 0;
      const rewardedLdc = Math.max(0, Number(data.rewarded_ldc || 0));
      const rewardedAccounts = Math.max(0, Number(data.rewarded_accounts || 0));

      const messages = [
        `已提交 ${matchedFiles} 个文件，共 ${accountsToImport.length} 个账户`,
      ];
      messages.push("这些账户会按捐赠账户入池");
      if ((data.skipped ?? 0) > 0) {
        messages.push(`跳过 ${data.skipped} 个重复项`);
      }
      if (rewardedLdc > 0) {
        messages.push(
          `有效 Free 账号 ${rewardedAccounts} 个，已到账 ${rewardedLdc} 积分`,
        );
      }
      if (errorCount > 0) {
        messages.push(`刷新失败 ${errorCount} 个`);
      }
      if (invalidFiles.length > 0) {
        messages.push(`${invalidFiles.length} 个文件不是有效 JSON`);
      }
      if (emptyFiles.length > 0) {
        messages.push(`${emptyFiles.length} 个文件没有可识别的 token 字段`);
      }

      await syncSession();
      if (errorCount > 0) {
        toast.error(messages.join("，"));
      } else {
        toast.success(messages.join("，"));
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "上传捐赠账户失败";
      toast.error(message);
    } finally {
      setIsUploadingDonation(false);
      if (uploadInputRef.current) {
        uploadInputRef.current.value = "";
      }
    }
  };

  const handleRedeemCode = async () => {
    const code = redeemInput.trim();
    if (!code) {
      toast.error("请先输入兑换码");
      return;
    }
    setIsRedeemingCode(true);
    try {
      const data = await redeemCode(code);
      await syncSession();
      window.dispatchEvent(new Event("chatgpt2api:quota-changed"));
      setRedeemInput("");
      toast.success(
        `兑换成功，已增加 ${Math.max(0, Number(data.added_quota || 0))} 额度，当前剩余 ${Math.max(0, Number(data.remaining_quota || 0))}`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "兑换失败";
      toast.error(message);
    } finally {
      setIsRedeemingCode(false);
    }
  };

  if (pathname === "/login") {
    return null;
  }

  const visibleNavItems = navItems.filter(
    (item) =>
      !item.roles ||
      (sessionState.role ? item.roles.includes(sessionState.role) : false),
  );
  const isUserKey = sessionState.authType === "user_key";

  return (
    <header className="minimal-topnav sticky top-0 z-30 -mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      <div className="mx-auto flex min-h-14 max-w-[1440px] min-w-0 items-center gap-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Link
            href="/image"
            className="rounded-lg px-2 py-2 text-base font-semibold text-foreground transition hover:bg-muted"
          >
            chatgpt2api
          </Link>
        </div>

        <nav className="hide-scrollbar flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {visibleNavItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "shrink-0 rounded-lg px-3 py-2 text-sm transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/20",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex shrink-0 items-center gap-2">
          <div className="hidden items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm text-foreground shadow-sm md:flex">
            <Palette className="size-4 text-muted-foreground" />
            <label className="sr-only" htmlFor="theme-mode-select">
              颜色模式
            </label>
            <select
              id="theme-mode-select"
              value={themeMode}
              onChange={(event) =>
                setThemeMode(event.target.value as ThemeMode)
              }
              className="bg-transparent text-sm text-foreground outline-none"
            >
              {themeModeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <Dialog open={centerOpen} onOpenChange={setCenterOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm text-foreground transition hover:bg-muted focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/20"
                aria-label="打开兑换中心"
              >
                <Ticket className="size-4" />
                <span className="hidden sm:inline">兑换中心</span>
              </button>
            </DialogTrigger>
            <DialogContent
              showCloseButton={false}
              className="p-5 sm:p-6"
            >
              <DialogHeader className="gap-2">
                <DialogTitle>兑换中心</DialogTitle>
                <DialogDescription className="text-sm leading-6">
                  购买兑换码后，把兑换码粘贴到下方即可给当前用户 key 增加额度。
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <div className="rounded-xl border border-border bg-muted/45 p-4">
                  <div className="text-xs text-muted-foreground">当前额度</div>
                  <div className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                    {sessionState.remainingQuota ?? "—"}
                  </div>
                </div>

                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".json,application/json"
                  multiple
                  className="hidden"
                  onChange={(event) =>
                    void handleDonationUpload(
                      Array.from(event.target.files ?? []),
                    )
                  }
                />

                <div className="rounded-xl border border-dashed border-border bg-muted/35 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <Gift className="size-4" />
                        捐赠换积分
                      </div>
                      <p className="text-xs leading-5 text-muted-foreground">
                        支持标准账号 JSON 和 CPA 格式 JSON。只有成功入池并识别成
                        Free 的账号才会给当前用户 key 发放 `20 积分`。
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-10 px-4"
                      onClick={() => uploadInputRef.current?.click()}
                      disabled={isUploadingDonation}
                    >
                      {isUploadingDonation ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <Upload className="size-4" />
                      )}
                      上传 JSON
                    </Button>
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-muted/35 p-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <Ticket className="size-4" />
                      购买兑换码
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {redeemCodePurchaseLinks.map((item) => (
                        <a
                          key={item.href}
                          href={item.href}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-lg border border-border bg-background px-4 py-3 text-sm transition hover:bg-muted"
                        >
                          <div className="font-semibold text-foreground">
                            {item.label}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            直达购买页面，购买后回来输入兑换码。
                          </div>
                        </a>
                      ))}
                    </div>
                    {!isUserKey ? (
                      <p className="text-xs leading-5 text-muted-foreground">
                        只有用户 key 才能在这里兑换额度。
                      </p>
                    ) : null}
                  </div>
                </div>

                <div className="rounded-xl border border-border bg-muted/35 p-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <Ticket className="size-4" />
                      兑换码
                    </div>
                    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                      <div className="space-y-2">
                        <label className="text-xs text-muted-foreground">
                          输入兑换码
                        </label>
                        <Input
                          value={redeemInput}
                          onChange={(event) =>
                            setRedeemInput(event.target.value)
                          }
                          placeholder="例如 RDM-XXXXXX"
                          className="h-11"
                        />
                      </div>
                      <Button
                        className="h-11 px-5"
                        onClick={() => void handleRedeemCode()}
                        disabled={!isUserKey || isRedeemingCode}
                      >
                        {isRedeemingCode ? (
                          <LoaderCircle className="size-4 animate-spin" />
                        ) : (
                          <Ticket className="size-4" />
                        )}
                        兑换
                      </Button>
                    </div>
                    <p className="text-xs leading-5 text-muted-foreground">
                      兑换成功后，会在当前用户 key 的剩余额度上增加对应额度。
                    </p>
                  </div>
                </div>
              </div>

              <DialogFooter className="pt-2">
                <Button
                  variant="outline"
                  className="h-10 px-5"
                  onClick={() => setCenterOpen(false)}
                  disabled={isUploadingDonation || isRedeemingCode}
                >
                  关闭
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <span className="hidden rounded-lg border border-border bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground md:inline-flex">
            v{webConfig.appVersion}
          </span>
          <button
            type="button"
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm text-foreground transition hover:bg-muted focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-ring/20"
            onClick={() => void handleLogout()}
            aria-label="退出"
          >
            <LogOut className="size-4" />
            <span className="hidden sm:inline">退出</span>
          </button>
        </div>
      </div>
    </header>
  );
}
