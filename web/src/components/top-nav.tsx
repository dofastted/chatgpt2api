"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Upload } from "lucide-react";
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
import webConfig from "@/constants/common-env";
import { cleanJsonText, extractAccessTokensFromJson, normalizeTokenList } from "@/lib/account-import";
import { createDonationAccounts, fetchAuthSession, type AuthRole } from "@/lib/api";
import { clearStoredAuthKey } from "@/store/auth";
import { cn } from "@/lib/utils";

const navItems: Array<{ href: string; label: string; roles?: AuthRole[] }> = [
  { href: "/image", label: "画图" },
  { href: "/accounts", label: "号池管理", roles: ["admin"] },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [authRole, setAuthRole] = useState<AuthRole | null>(null);
  const [donationOpen, setDonationOpen] = useState(false);
  const [isUploadingDonation, setIsUploadingDonation] = useState(false);

  useEffect(() => {
    if (pathname === "/login") {
      return;
    }

    let cancelled = false;
    const loadSession = async () => {
      try {
        const session = await fetchAuthSession();
        if (!cancelled) {
          setAuthRole(session.role);
        }
      } catch {
        if (!cancelled) {
          setAuthRole(null);
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
      const importedTokens: string[] = [];
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
          const fileTokens = extractAccessTokensFromJson(payload);
          if (fileTokens.length === 0) {
            emptyFiles.push(file.name);
            continue;
          }

          matchedFiles += 1;
          importedTokens.push(...fileTokens);
        } catch {
          invalidFiles.push(file.name);
        }
      }

      const tokens = normalizeTokenList(importedTokens);
      if (tokens.length === 0) {
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

      const data = await createDonationAccounts(tokens);
      const errorCount = data.errors?.length ?? 0;
      const rewardedQuota = Math.max(0, Number(data.rewarded_quota || 0));
      const rewardedAccounts = Math.max(0, Number(data.rewarded_accounts || 0));
      setDonationOpen(false);

      const messages = [`已提交 ${matchedFiles} 个文件，共 ${tokens.length} 个 Token`];
      messages.push("这些账户会按捐赠账户入池");
      if ((data.skipped ?? 0) > 0) {
        messages.push(`跳过 ${data.skipped} 个重复项`);
      }
      if (rewardedQuota > 0) {
        messages.push(`捐赠成功 ${rewardedAccounts} 个，用户 key 已到账 ${rewardedQuota} 点`);
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

      if (errorCount > 0) {
        toast.error(messages.join("，"));
      } else {
        toast.success(messages.join("，"));
      }
      if (rewardedQuota > 0) {
        window.dispatchEvent(new Event("chatgpt2api:quota-changed"));
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

  if (pathname === "/login") {
    return null;
  }

  const visibleNavItems = navItems.filter((item) => !item.roles || (authRole ? item.roles.includes(authRole) : false));

  return (
    <header>
      <div className="flex h-12 items-start justify-between pt-1">
        <div className="flex flex-1 items-center gap-3">
          <Link
            href="/image"
            className="py-2 text-[15px] font-semibold tracking-tight text-stone-950 transition hover:text-stone-700"
          >
            chatgpt2api
          </Link>
          <Dialog open={donationOpen} onOpenChange={setDonationOpen}>
            <DialogTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 py-2 text-sm text-stone-400 transition hover:text-stone-700"
                aria-label="上传捐赠账户"
              >
                <Upload className="size-4" />
                <span>捐赠上传</span>
              </button>
            </DialogTrigger>
            <DialogContent showCloseButton={false} className="rounded-2xl p-6">
              <DialogHeader className="gap-2">
                <DialogTitle>捐赠账户上传</DialogTitle>
                <DialogDescription className="text-sm leading-6">
                  支持标准账号 JSON 和 CPA 格式 JSON。系统会自动识别 `access_token`、`accessToken`、`token` 等字段，并把导入账号标记为捐赠账户。
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
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
                      <div className="text-sm font-medium text-stone-800">上传 JSON</div>
                      <p className="text-xs leading-5 text-stone-500">
                        支持多选文件，也支持 CPA 格式 JSON。导入成功后，这些账号会被归到捐赠账户，但仍会计入号池。
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
                      选择文件
                    </Button>
                  </div>
                </div>
              </div>
              <DialogFooter className="pt-2">
                <Button
                  variant="secondary"
                  className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
                  onClick={() => setDonationOpen(false)}
                  disabled={isUploadingDonation}
                >
                  关闭
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
        <div className="flex justify-center gap-8">
          {visibleNavItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "relative py-2 text-[15px] font-medium transition",
                  active ? "font-semibold text-stone-950" : "text-stone-500 hover:text-stone-900",
                )}
              >
                {item.label}
                {active ? <span className="absolute inset-x-0 -bottom-[3px] h-0.5 bg-stone-950" /> : null}
              </Link>
            );
          })}
        </div>
        <div className="flex flex-1 items-center justify-end gap-3">
          <span className="rounded-md bg-stone-100 px-2 py-1 text-[11px] font-medium text-stone-500">
            v{webConfig.appVersion}
          </span>
          <button
            type="button"
            className="py-2 text-sm text-stone-400 transition hover:text-stone-700"
            onClick={() => void handleLogout()}
          >
            退出
          </button>
        </div>
      </div>
    </header>
  );
}
