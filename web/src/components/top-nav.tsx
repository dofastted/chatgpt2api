"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Gift, LoaderCircle, Ticket, Upload } from "lucide-react";
import { toast } from "sonner";

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

  const syncSession = async () => {
    const session = await fetchAuthSession({ redirectOnUnauthorized: false, retries: 1 });
    setSessionState({
      role: session.role,
      authType: session.auth_type ?? null,
      remainingQuota:
        session.remaining_quota === null || session.remaining_quota === undefined
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
        const session = await fetchAuthSession({ redirectOnUnauthorized: false, retries: 1 });
        if (!cancelled) {
          setSessionState({
            role: session.role,
            authType: session.auth_type ?? null,
              remainingQuota:
                session.remaining_quota === null || session.remaining_quota === undefined
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
      const importedAccounts: Array<{ access_token: string; [key: string]: unknown }> = [];
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

      const indexedAccounts = new Map<string, { access_token: string; [key: string]: unknown }>();
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
        toast.error(errors.length > 0 ? `未提取到可用 Token，${errors.join("，")}` : "未提取到可用 Token");
        return;
      }

      const data = await createDonationAccounts({ accounts: accountsToImport });
      const errorCount = data.errors?.length ?? 0;
      const rewardedLdc = Math.max(0, Number(data.rewarded_ldc || 0));
      const rewardedAccounts = Math.max(0, Number(data.rewarded_accounts || 0));

      const messages = [`已提交 ${matchedFiles} 个文件，共 ${accountsToImport.length} 个账户`];
      messages.push("这些账户会按捐赠账户入池");
      if ((data.skipped ?? 0) > 0) {
        messages.push(`跳过 ${data.skipped} 个重复项`);
      }
      if (rewardedLdc > 0) {
        messages.push(`有效 Free 账号 ${rewardedAccounts} 个，已到账 ${rewardedLdc} 积分`);
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
      const message = error instanceof Error ? error.message : "上传捐赠账户失败";
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
    (item) => !item.roles || (sessionState.role ? item.roles.includes(sessionState.role) : false),
  );
  const isUserKey = sessionState.authType === "user_key";

  return (
    <header className="max-topnav">
      <div className="relative flex min-h-[84px] flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 items-center gap-3">
          <Link
            href="/image"
            className="relative py-2 font-['Outfit'] text-lg font-black uppercase tracking-[0.22em] text-[#FFE600] transition hover:text-white"
          >
            chatgpt2api
          </Link>
          <Dialog open={centerOpen} onOpenChange={setCenterOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center gap-2 rounded-full border-2 border-dashed border-[#FF6B35] bg-[#FF6B35]/12 px-4 py-2 text-sm font-bold uppercase tracking-[0.16em] text-white transition hover:border-[#FFE600] hover:bg-[#FF3AF2]/18"
                aria-label="打开兑换中心"
              >
                <Ticket className="size-4" />
                <span>兑换中心</span>
              </button>
            </DialogTrigger>
            <DialogContent showCloseButton={false} className="rounded-2xl p-6">
              <DialogHeader className="gap-2">
                <DialogTitle>兑换中心</DialogTitle>
                <DialogDescription className="text-sm leading-6">
                  购买兑换码后，把兑换码粘贴到下方即可给当前用户 key 增加额度。
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-4">
                <div className="rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
                  <div className="text-xs text-stone-400">当前额度</div>
                  <div className="mt-1 text-2xl font-semibold tracking-tight text-stone-900">
                    {sessionState.remainingQuota ?? "—"}
                  </div>
                </div>

                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".json,application/json"
                  multiple
                  className="hidden"
                  onChange={(event) => void handleDonationUpload(Array.from(event.target.files ?? []))}
                />

                <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50/70 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 text-sm font-medium text-stone-800">
                        <Gift className="size-4" />
                        捐赠换积分
                      </div>
                      <p className="text-xs leading-5 text-stone-500">
                        支持标准账号 JSON 和 CPA 格式 JSON。只有成功入池并识别成 Free 的账号才会给当前用户 key 发放 `20 积分`。
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700 hover:bg-stone-100"
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

                <div className="rounded-2xl border border-stone-200 bg-white p-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-stone-800">
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
                          className="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm transition hover:border-stone-300 hover:bg-stone-100"
                        >
                          <div className="font-semibold text-stone-900">{item.label}</div>
                          <div className="mt-1 text-xs text-stone-500">直达购买页面，购买后回来输入兑换码。</div>
                        </a>
                      ))}
                    </div>
                    {!isUserKey ? (
                      <p className="text-xs leading-5 text-stone-400">只有用户 key 才能在这里兑换额度。</p>
                    ) : null}
                  </div>
                </div>

                <div className="rounded-2xl border border-stone-200 bg-white p-4">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-stone-800">
                      <Ticket className="size-4" />
                      兑换码
                    </div>
                    <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                      <div className="space-y-2">
                        <label className="text-xs text-stone-500">输入兑换码</label>
                        <Input
                          value={redeemInput}
                          onChange={(event) => setRedeemInput(event.target.value)}
                          placeholder="例如 RDM-XXXXXX"
                          className="h-11 rounded-xl border-stone-200 bg-white"
                        />
                      </div>
                      <Button
                        className="h-11 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                        onClick={() => void handleRedeemCode()}
                        disabled={!isUserKey || isRedeemingCode}
                      >
                        {isRedeemingCode ? <LoaderCircle className="size-4 animate-spin" /> : <Ticket className="size-4" />}
                        兑换
                      </Button>
                    </div>
                    <p className="text-xs leading-5 text-stone-500">
                      兑换成功后，会在当前用户 key 的剩余额度上增加对应额度。
                    </p>
                  </div>
                </div>
              </div>

              <DialogFooter className="pt-2">
                <Button
                  variant="secondary"
                  className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
                  onClick={() => setCenterOpen(false)}
                  disabled={isUploadingDonation || isRedeemingCode}
                >
                  关闭
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
        <div className="flex flex-wrap justify-center gap-3 lg:gap-4">
          {visibleNavItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative rounded-full border-2 px-4 py-2 text-sm font-black uppercase tracking-[0.16em] transition",
                  active
                    ? "border-[#FFE600] bg-[#FF3AF2]/18 text-white"
                    : "border-[#00F5D4]/55 bg-white/5 text-white/78 hover:border-[#00F5D4] hover:text-white",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </div>
        <div className="flex flex-1 items-center justify-end gap-3">
          <span className="rounded-full border-2 border-[#7B2FFF] bg-[#7B2FFF]/18 px-3 py-1 text-[11px] font-black uppercase tracking-[0.14em] text-white/80">
            v{webConfig.appVersion}
          </span>
          <button
            type="button"
            className="rounded-full border-2 border-[#FF3AF2]/65 bg-[#FF3AF2]/12 px-4 py-2 text-sm font-black uppercase tracking-[0.16em] text-white transition hover:border-[#FFE600] hover:bg-[#FF3AF2]/24"
            onClick={() => void handleLogout()}
          >
            退出
          </button>
        </div>
      </div>
    </header>
  );
}
