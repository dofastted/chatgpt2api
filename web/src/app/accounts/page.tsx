"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentProps } from "react";
import {
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleOff,
  Copy,
  Download,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { cleanJsonText, extractAccessTokensFromJson, normalizeTokenList } from "@/lib/account-import";
import {
  createAccounts,
  createUserKeys,
  deleteAccounts,
  deleteUserKeys,
  fetchAuthSession,
  fetchAccounts,
  fetchUserKeys,
  refreshAccounts,
  updateAccount,
  updateUserKey,
  type Account,
  type AccountCategory,
  type AccountStatus,
  type AccountType,
  type UserKey,
  type UserKeyStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const accountTypeOptions: { label: string; value: AccountType | "all" }[] = [
  { label: "全部类型", value: "all" },
  { label: "Free", value: "Free" },
  { label: "Plus", value: "Plus" },
  { label: "Team", value: "Team" },
  { label: "Pro", value: "Pro" },
];

const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] = [
  { label: "全部状态", value: "all" },
  { label: "正常", value: "正常" },
  { label: "限流", value: "限流" },
  { label: "异常", value: "异常" },
  { label: "禁用", value: "禁用" },
];

const accountCategoryOptions: { label: string; value: AccountCategory | "all" }[] = [
  { label: "全部来源", value: "all" },
  { label: "普通", value: "普通" },
  { label: "捐赠", value: "捐赠" },
];

const statusMeta: Record<
  AccountStatus,
  {
    icon: typeof CheckCircle2;
    badge: ComponentProps<typeof Badge>["variant"];
  }
> = {
  正常: { icon: CheckCircle2, badge: "success" },
  限流: { icon: CircleAlert, badge: "warning" },
  异常: { icon: CircleOff, badge: "danger" },
  禁用: { icon: Ban, badge: "secondary" },
};

const metricCards = [
  { key: "total", label: "账户总数", color: "text-stone-900", icon: UserRound },
  { key: "active", label: "正常账户", color: "text-emerald-600", icon: CheckCircle2 },
  { key: "limited", label: "限流账户", color: "text-orange-500", icon: CircleAlert },
  { key: "abnormal", label: "异常账户", color: "text-rose-500", icon: CircleOff },
  { key: "disabled", label: "禁用账户", color: "text-stone-500", icon: Ban },
  { key: "quota", label: "剩余额度", color: "text-blue-500", icon: RefreshCw },
] as const;

function formatCompact(value: number) {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function formatQuota(value: number) {
  return String(Math.max(0, value));
}

function formatRestoreAt(value?: string | null) {
  if (!value) {
    return { absolute: "—", relative: "" };
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return { absolute: value, relative: "" };
  }

  const diffMs = Math.max(0, date.getTime() - Date.now());
  const totalHours = Math.ceil(diffMs / (1000 * 60 * 60));
  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  const relative = diffMs > 0 ? `剩余 ${days}d ${hours}h` : "已到恢复时间";

  const pad = (num: number) => String(num).padStart(2, "0");
  const absolute = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;

  return { absolute, relative };
}

function formatQuotaSummary(accounts: Account[]) {
  return formatCompact(accounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0));
}

function formatUserKeyQuotaSummary(userKeys: UserKey[]) {
  return formatCompact(userKeys.reduce((sum, item) => sum + Math.max(0, item.quota), 0));
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const pad = (num: number) => String(num).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}:${pad(date.getSeconds())}`;
}

function maskToken(token?: string) {
  if (!token) return "—";
  if (token.length <= 18) return token;
  return `${token.slice(0, 16)}...${token.slice(-8)}`;
}

function downloadTokens(accounts: Account[]) {
  const content = `${accounts.map((account) => account.access_token).join("\n")}\n`;
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `accounts-${Date.now()}.txt`;
  link.click();
  URL.revokeObjectURL(url);
}

function normalizeAccounts(items: Account[]): Account[] {
  return items.map((item) => ({
    ...item,
    category: item.category === "捐赠" ? "捐赠" : "普通",
    type:
      item.type === "Plus" || item.type === "Team" || item.type === "Pro" || item.type === "Free"
        ? item.type
        : "Free",
  }));
}

export default function AccountsPage() {
  const router = useRouter();
  const didLoadRef = useRef(false);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [userKeys, setUserKeys] = useState<UserKey[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [userKeyQuery, setUserKeyQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<AccountCategory | "all">("all");
  const [typeFilter, setTypeFilter] = useState<AccountType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<AccountStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("10");
  const [open, setOpen] = useState(false);
  const [newTokens, setNewTokens] = useState("");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editingUserKey, setEditingUserKey] = useState<UserKey | null>(null);
  const [editCategory, setEditCategory] = useState<AccountCategory>("普通");
  const [editType, setEditType] = useState<AccountType>("Free");
  const [editStatus, setEditStatus] = useState<AccountStatus>("正常");
  const [editQuota, setEditQuota] = useState("0");
  const [newUserKeyPrefix, setNewUserKeyPrefix] = useState("uk");
  const [newUserKeyLabelPrefix, setNewUserKeyLabelPrefix] = useState("");
  const [newUserKeyCount, setNewUserKeyCount] = useState("5");
  const [newUserKeyQuota, setNewUserKeyQuota] = useState("20");
  const [editUserKeyLabel, setEditUserKeyLabel] = useState("");
  const [editUserKeyQuota, setEditUserKeyQuota] = useState("0");
  const [editUserKeyStatus, setEditUserKeyStatus] = useState<UserKeyStatus>("启用");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isUploadingJson, setIsUploadingJson] = useState(false);
  const [isLoadingUserKeys, setIsLoadingUserKeys] = useState(true);
  const [isSubmittingUserKeys, setIsSubmittingUserKeys] = useState(false);
  const [isDeletingUserKeys, setIsDeletingUserKeys] = useState(false);
  const [isUpdatingUserKey, setIsUpdatingUserKey] = useState(false);
  const [isAuthorizing, setIsAuthorizing] = useState(true);

  const loadAccounts = async (silent = false) => {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchAccounts();
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.id === id)));
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载账户失败";
      toast.error(message);
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;

    let cancelled = false;
    const bootstrap = async () => {
      try {
        const session = await fetchAuthSession();
        if (cancelled) {
          return;
        }
        if (session.role !== "admin") {
          toast.error("当前密钥没有号池管理权限");
          router.replace("/image");
          return;
        }
        setIsAuthorizing(false);
        await Promise.all([loadAccounts(), loadUserKeys()]);
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const filteredAccounts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return accounts.filter((account) => {
      const searchMatched =
        normalizedQuery.length === 0 || (account.email ?? "").toLowerCase().includes(normalizedQuery);
      const categoryMatched = categoryFilter === "all" || account.category === categoryFilter;
      const typeMatched = typeFilter === "all" || account.type === typeFilter;
      const statusMatched = statusFilter === "all" || account.status === statusFilter;
      return searchMatched && categoryMatched && typeMatched && statusMatched;
    });
  }, [accounts, categoryFilter, query, statusFilter, typeFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredAccounts.length / Number(pageSize)));
  const safePage = Math.min(page, pageCount);
  const startIndex = (safePage - 1) * Number(pageSize);
  const currentRows = filteredAccounts.slice(startIndex, startIndex + Number(pageSize));
  const allCurrentSelected =
    currentRows.length > 0 && currentRows.every((row) => selectedIds.includes(row.id));

  const summary = useMemo(() => {
    const total = accounts.length;
    const active = accounts.filter((item) => item.status === "正常").length;
    const limited = accounts.filter((item) => item.status === "限流").length;
    const abnormal = accounts.filter((item) => item.status === "异常").length;
    const disabled = accounts.filter((item) => item.status === "禁用").length;
    const quota = formatQuotaSummary(accounts);

    return { total, active, limited, abnormal, disabled, quota };
  }, [accounts]);

  const selectedTokens = useMemo(() => {
    const selectedSet = new Set(selectedIds);
    return accounts.filter((item) => selectedSet.has(item.id)).map((item) => item.access_token);
  }, [accounts, selectedIds]);

  const abnormalTokens = useMemo(() => {
    return accounts.filter((item) => item.status === "异常").map((item) => item.access_token);
  }, [accounts]);

  const filteredUserKeys = useMemo(() => {
    const normalizedQuery = userKeyQuery.trim().toLowerCase();
    return userKeys.filter((item) => {
      if (normalizedQuery.length === 0) {
        return true;
      }
      return (
        item.key.toLowerCase().includes(normalizedQuery) ||
        String(item.label || "")
          .toLowerCase()
          .includes(normalizedQuery)
      );
    });
  }, [userKeyQuery, userKeys]);

  const userKeySummary = useMemo(() => {
    const total = userKeys.length;
    const enabled = userKeys.filter((item) => item.status === "启用").length;
    const disabled = userKeys.filter((item) => item.status === "停用").length;
    const quota = formatUserKeyQuotaSummary(userKeys);
    return { total, enabled, disabled, quota };
  }, [userKeys]);

  const paginationItems = useMemo(() => {
    const items: (number | "...")[] = [];
    const start = Math.max(1, safePage - 1);
    const end = Math.min(pageCount, safePage + 1);

    if (start > 1) items.push(1);
    if (start > 2) items.push("...");
    for (let current = start; current <= end; current += 1) items.push(current);
    if (end < pageCount - 1) items.push("...");
    if (end < pageCount) items.push(pageCount);

    return items;
  }, [pageCount, safePage]);

  if (isAuthorizing) {
    return (
      <div className="grid min-h-[calc(100vh-6rem)] place-items-center">
        <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
          <LoaderCircle className="size-5 animate-spin" />
        </div>
      </div>
    );
  }

  const handleAddAccounts = async () => {
    const tokens = normalizeTokenList(newTokens.split(/\r?\n/));

    if (tokens.length === 0) {
      toast.error("请先粘贴至少一个 Access Token");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await createAccounts(tokens);
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds([]);
      setOpen(false);
      setNewTokens("");
      setPage(1);
      if ((data.errors?.length ?? 0) > 0) {
        const firstError = data.errors?.[0]?.error;
        toast.error(
          `新增 ${data.added ?? 0} 个账户，已刷新 ${data.refreshed ?? 0} 个，失败 ${data.errors?.length ?? 0} 个${firstError ? `，首个错误：${firstError}` : ""}`,
        );
      } else {
        toast.success(`新增 ${data.added ?? 0} 个账户，跳过 ${data.skipped ?? 0} 个重复项，已自动刷新账号信息`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "新增账户失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const loadUserKeys = async (silent = false) => {
    if (!silent) {
      setIsLoadingUserKeys(true);
    }
    try {
      const data = await fetchUserKeys();
      setUserKeys(data.items);
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载用户 key 失败";
      toast.error(message);
    } finally {
      if (!silent) {
        setIsLoadingUserKeys(false);
      }
    }
  };

  const handleUploadJsonAccounts = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setIsUploadingJson(true);

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
          errors.push(`${emptyFiles.length} 个文件没有 access_token`);
        }
        toast.error(errors.length > 0 ? `未提取到可用 Token，${errors.join("，")}` : "未提取到可用 Token");
        return;
      }

      const data = await createAccounts(tokens);
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds([]);
      setNewTokens("");
      setPage(1);
      setOpen(false);

      const messages = [`已从 ${matchedFiles} 个文件导入 ${tokens.length} 个 Token`];
      if ((data.skipped ?? 0) > 0) {
        messages.push(`跳过 ${data.skipped} 个重复项`);
      }
      if ((data.errors?.length ?? 0) > 0) {
        messages.push(`刷新失败 ${data.errors?.length ?? 0} 个`);
      }
      if (invalidFiles.length > 0) {
        messages.push(`${invalidFiles.length} 个文件不是有效 JSON`);
      }
      if (emptyFiles.length > 0) {
        messages.push(`${emptyFiles.length} 个文件没有 access_token`);
      }

      if ((data.errors?.length ?? 0) > 0) {
        toast.error(messages.join("，"));
      } else {
        toast.success(messages.join("，"));
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "上传 JSON 失败";
      toast.error(message);
    } finally {
      setIsUploadingJson(false);
      if (uploadInputRef.current) {
        uploadInputRef.current.value = "";
      }
    }
  };

  const handleDeleteTokens = async (tokens: string[]) => {
    if (tokens.length === 0) {
      toast.error("请先选择要删除的账户");
      return;
    }

    setIsDeleting(true);
    try {
      const data = await deleteAccounts(tokens);
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.id === id)));
      toast.success(`删除 ${data.removed ?? 0} 个账户`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除账户失败";
      toast.error(message);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRefreshAccounts = async (accessTokens: string[]) => {
    if (accessTokens.length === 0) {
      toast.error("没有需要刷新的账户");
      return;
    }

    setIsRefreshing(true);
    try {
      const data = await refreshAccounts(accessTokens);
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.id === id)));
      if (data.errors.length > 0) {
        const firstError = data.errors[0]?.error;
        toast.error(
          `刷新成功 ${data.refreshed} 个，失败 ${data.errors.length} 个${firstError ? `，首个错误：${firstError}` : ""}`,
        );
      } else {
        toast.success(`刷新成功 ${data.refreshed} 个账户`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "刷新账户失败";
      toast.error(message);
    } finally {
      setIsRefreshing(false);
    }
  };

  const openEditDialog = (account: Account) => {
    setEditingAccount(account);
    setEditCategory(account.category);
    setEditType(account.type);
    setEditStatus(account.status);
    setEditQuota(String(account.quota));
  };

  const handleUpdateAccount = async () => {
    if (!editingAccount) {
      return;
    }

    setIsUpdating(true);
    try {
      const data = await updateAccount(editingAccount.access_token, {
        category: editCategory,
        type: editType,
        status: editStatus,
        quota: Number(editQuota || 0),
      });
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds((prev) => prev.filter((id) => data.items.some((item) => item.id === id)));
      setEditingAccount(null);
      toast.success("账号信息已更新");
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新账号失败";
      toast.error(message);
    } finally {
      setIsUpdating(false);
    }
  };

  const openUserKeyDialog = (userKey: UserKey) => {
    setEditingUserKey(userKey);
    setEditUserKeyLabel(String(userKey.label || ""));
    setEditUserKeyQuota(String(userKey.quota));
    setEditUserKeyStatus(userKey.status);
  };

  const handleCreateUserKeys = async () => {
    setIsSubmittingUserKeys(true);
    try {
      const data = await createUserKeys({
        count: Math.max(1, Number(newUserKeyCount || 1)),
        quota: Math.max(0, Number(newUserKeyQuota || 0)),
        prefix: newUserKeyPrefix.trim() || undefined,
        label_prefix: newUserKeyLabelPrefix.trim() || undefined,
      });
      setUserKeys(data.items);
      toast.success(`已生成 ${data.created_items?.length ?? data.added ?? 0} 个用户 key`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "生成用户 key 失败";
      toast.error(message);
    } finally {
      setIsSubmittingUserKeys(false);
    }
  };

  const handleDeleteUserKey = async (key: string) => {
    setIsDeletingUserKeys(true);
    try {
      const data = await deleteUserKeys([key]);
      setUserKeys(data.items);
      setEditingUserKey((prev) => (prev?.key === key ? null : prev));
      toast.success(`已删除 ${data.removed ?? 0} 个用户 key`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除用户 key 失败";
      toast.error(message);
    } finally {
      setIsDeletingUserKeys(false);
    }
  };

  const handleUpdateUserKey = async () => {
    if (!editingUserKey) {
      return;
    }
    setIsUpdatingUserKey(true);
    try {
      const data = await updateUserKey(editingUserKey.key, {
        label: editUserKeyLabel.trim() || undefined,
        quota: Math.max(0, Number(editUserKeyQuota || 0)),
        status: editUserKeyStatus,
      });
      setUserKeys(data.items);
      setEditingUserKey(null);
      toast.success("用户 key 已更新");
    } catch (error) {
      const message = error instanceof Error ? error.message : "更新用户 key 失败";
      toast.error(message);
    } finally {
      setIsUpdatingUserKey(false);
    }
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentRows.map((item) => item.id)])));
      return;
    }
    setSelectedIds((prev) => prev.filter((id) => !currentRows.some((row) => row.id === id)));
  };

  return (
    <>
      <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
            Account Pool
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">号池管理</h1>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => void loadAccounts()}
            disabled={isLoading || isRefreshing || isSubmitting || isDeleting}
          >
            <RefreshCw className={cn("size-4", isLoading ? "animate-spin" : "")} />
            刷新
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => void handleRefreshAccounts(accounts.map((item) => item.access_token))}
            disabled={isLoading || isRefreshing || isSubmitting || isDeleting || accounts.length === 0}
          >
            <RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
            一键刷新所有账号信息和额度
          </Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
                <Plus className="size-4" />
                新增
              </Button>
            </DialogTrigger>
            <DialogContent showCloseButton={false} className="rounded-2xl p-6">
              <DialogHeader className="gap-2">
                <DialogTitle>新增账户</DialogTitle>
                <DialogDescription className="text-sm leading-6">
                  支持批量上传 JSON 文件直接导入，也支持手动粘贴 Access Token。
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <input
                  ref={uploadInputRef}
                  type="file"
                  accept=".json,application/json"
                  multiple
                  className="hidden"
                  onChange={(event) => void handleUploadJsonAccounts(Array.from(event.target.files ?? []))}
                />
                <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50/70 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-stone-800">批量上传 JSON</div>
                      <p className="text-xs leading-5 text-stone-500">
                        可多选文件，系统会清洗内容并提取其中的 access_token，然后直接调用新增接口。
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700 hover:bg-stone-100"
                      onClick={() => uploadInputRef.current?.click()}
                      disabled={isSubmitting || isUploadingJson}
                    >
                      {isUploadingJson ? <LoaderCircle className="size-4 animate-spin" /> : <Upload className="size-4" />}
                      上传 JSON
                    </Button>
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-stone-700">Token 列表</label>
                  <Textarea
                    placeholder="粘贴 Token，每行一个..."
                    value={newTokens}
                    onChange={(event) => setNewTokens(event.target.value)}
                    className="min-h-48 resize-none rounded-xl border-stone-200"
                  />
                </div>
              </div>
              <DialogFooter className="pt-2">
                <Button
                  variant="secondary"
                  className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
                  onClick={() => setOpen(false)}
                  disabled={isSubmitting}
                >
                  取消
                </Button>
                <Button
                  className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
                  onClick={() => void handleAddAccounts()}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
                  新增账户
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => downloadTokens(accounts)}
            disabled={accounts.length === 0}
          >
            <Download className="size-4" />
            导出全部 Token
          </Button>
        </div>
      </section>

      <Dialog open={Boolean(editingAccount)} onOpenChange={(open) => (!open ? setEditingAccount(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>编辑账户</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              手动修改账户来源、状态、类型和额度。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">来源</label>
              <Select value={editCategory} onValueChange={(value) => setEditCategory(value as AccountCategory)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountCategoryOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">状态</label>
              <Select value={editStatus} onValueChange={(value) => setEditStatus(value as AccountStatus)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountStatusOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">类型</label>
              <Select value={editType} onValueChange={(value) => setEditType(value as AccountType)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {accountTypeOptions
                    .filter((option) => option.value !== "all")
                    .map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">额度</label>
              <Input
                value={editQuota}
                onChange={(event) => setEditQuota(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setEditingAccount(null)}
              disabled={isUpdating}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleUpdateAccount()}
              disabled={isUpdating}
            >
              {isUpdating ? <LoaderCircle className="size-4 animate-spin" /> : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(editingUserKey)} onOpenChange={(open) => (!open ? setEditingUserKey(null) : null)}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>编辑用户 key</DialogTitle>
            <DialogDescription className="text-sm leading-6">手动修改标签、状态和剩余次数。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">标签</label>
              <Input
                value={editUserKeyLabel}
                onChange={(event) => setEditUserKeyLabel(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
                placeholder="可留空"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">状态</label>
              <Select value={editUserKeyStatus} onValueChange={(value) => setEditUserKeyStatus(value as UserKeyStatus)}>
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="启用">启用</SelectItem>
                  <SelectItem value="停用">停用</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">剩余次数</label>
              <Input
                value={editUserKeyQuota}
                onChange={(event) => setEditUserKeyQuota(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setEditingUserKey(null)}
              disabled={isUpdatingUserKey}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleUpdateUserKey()}
              disabled={isUpdatingUserKey}
            >
              {isUpdatingUserKey ? <LoaderCircle className="size-4 animate-spin" /> : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <section className="space-y-3">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
          {metricCards.map((item) => {
            const Icon = item.icon;
            const value = summary[item.key];
            return (
              <Card key={item.key} className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
                <CardContent className="p-4">
                  <div className="mb-4 flex items-start justify-between">
                    <span className="text-xs font-medium text-stone-400">{item.label}</span>
                    <Icon className="size-4 text-stone-400" />
                  </div>
                  <div className={cn("text-[1.75rem] font-semibold tracking-tight", item.color)}>
                    <span className={typeof value === "number" ? "" : "text-[1.1rem]"}>
                      {typeof value === "number" ? formatCompact(value) : value}
                    </span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">账户列表</h2>
            <Badge variant="secondary" className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700">
              {filteredAccounts.length}
            </Badge>
          </div>

          <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
            <div className="relative min-w-[260px]">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
              <Input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="搜索邮箱"
                className="h-10 rounded-xl border-stone-200 bg-white/85 pl-10"
              />
            </div>
            <Select
              value={categoryFilter}
              onValueChange={(value) => {
                setCategoryFilter(value as AccountCategory | "all");
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountCategoryOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={typeFilter}
              onValueChange={(value) => {
                setTypeFilter(value as AccountType | "all");
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountTypeOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as AccountStatus | "all");
                setPage(1);
              }}
            >
              <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white/85 lg:w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {accountStatusOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {isLoading && accounts.length === 0 ? (
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
              <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                <LoaderCircle className="size-5 animate-spin" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium text-stone-700">正在加载账户</p>
                <p className="text-sm text-stone-500">从后端同步账号列表和状态。</p>
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Card
          className={cn(
            "overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm",
            isLoading && accounts.length === 0 ? "hidden" : "",
          )}
        >
          <CardContent className="space-y-0 p-0">
            <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-2 text-sm text-stone-500">
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-stone-500 hover:bg-stone-100"
                  onClick={() => void handleRefreshAccounts(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isRefreshing}
                >
                  {isRefreshing ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  刷新选中账号信息和额度
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(abnormalTokens)}
                  disabled={abnormalTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  移除异常账号
                </Button>
                <Button
                  variant="ghost"
                  className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                  onClick={() => void handleDeleteTokens(selectedTokens)}
                  disabled={selectedTokens.length === 0 || isDeleting}
                >
                  {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                  删除所选
                </Button>
                {selectedIds.length > 0 ? (
                  <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                    已选择 {selectedIds.length} 项
                  </span>
                ) : null}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-left">
                <thead className="border-b border-stone-100 text-[11px] text-stone-400 uppercase tracking-[0.18em]">
                  <tr>
                    <th className="w-12 px-4 py-3">
                      <Checkbox
                        checked={allCurrentSelected}
                        onCheckedChange={(checked) => toggleSelectAll(Boolean(checked))}
                      />
                    </th>
                    <th className="w-56 px-4 py-3">token</th>
                    <th className="w-24 px-4 py-3">来源</th>
                    <th className="w-28 px-4 py-3">类型</th>
                    <th className="w-24 px-4 py-3">状态</th>
                    <th className="w-56 px-4 py-3">账号信息</th>
                    <th className="w-24 px-4 py-3">额度</th>
                    <th className="w-40 px-4 py-3">恢复时间</th>
                    <th className="w-18 px-4 py-3">成功</th>
                    <th className="w-18 px-4 py-3">失败</th>
                    <th className="w-24 px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {currentRows.map((account) => {
                    const status = statusMeta[account.status];
                    const StatusIcon = status.icon;

                    return (
                      <tr
                        key={account.id}
                        className="border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70"
                      >
                        <td className="px-4 py-3">
                          <Checkbox
                            checked={selectedIds.includes(account.id)}
                            onCheckedChange={(checked) => {
                              setSelectedIds((prev) =>
                                checked
                                  ? Array.from(new Set([...prev, account.id]))
                                  : prev.filter((item) => item !== account.id),
                              );
                            }}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-medium tracking-tight text-stone-700">
                              {maskToken(account.access_token)}
                            </span>
                            <button
                              type="button"
                              className="rounded-lg p-1 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                              onClick={() => {
                                void navigator.clipboard.writeText(account.access_token);
                                toast.success("token 已复制");
                              }}
                            >
                              <Copy className="size-4" />
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={account.category === "捐赠" ? "info" : "secondary"}
                            className="rounded-md"
                          >
                            {account.category}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary" className="rounded-md bg-stone-100 text-stone-700">
                            {account.type}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={status.badge}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1"
                          >
                            <StatusIcon className="size-3.5" />
                            {account.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="text-xs leading-5 text-stone-500">{account.email ?? "—"}</div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="info" className="rounded-md">
                            {formatQuota(account.quota)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs leading-5 text-stone-500">
                          {(() => {
                            const restore = formatRestoreAt(account.restoreAt);
                            return (
                              <div className="space-y-0.5">
                                {restore.relative ? <div className="font-medium text-stone-700">{restore.relative}</div> : null}
                                <div>{restore.absolute}</div>
                              </div>
                            );
                          })()}
                        </td>
                        <td className="px-4 py-3 text-stone-500">{account.success}</td>
                        <td className="px-4 py-3 text-stone-500">{account.fail}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1 text-stone-400">
                            <button
                              type="button"
                              className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
                              onClick={() => openEditDialog(account)}
                              disabled={isUpdating}
                            >
                              <Pencil className="size-4" />
                            </button>
                            <button
                              type="button"
                              className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
                              onClick={() => void handleRefreshAccounts([account.access_token])}
                              disabled={isRefreshing}
                            >
                              <RefreshCw className={cn("size-4", isRefreshing ? "animate-spin" : "")} />
                            </button>
                            <button
                              type="button"
                              className="rounded-lg p-2 transition hover:bg-rose-50 hover:text-rose-500"
                              onClick={() => void handleDeleteTokens([account.access_token])}
                              disabled={isDeleting}
                            >
                              <Trash2 className="size-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {!isLoading && currentRows.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <Search className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">没有匹配的账户</p>
                    <p className="text-sm text-stone-500">调整筛选条件或搜索关键字后重试。</p>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="border-t border-stone-100 px-4 py-4">
              <div className="flex items-center justify-center gap-3 overflow-x-auto whitespace-nowrap">
                <div className="shrink-0 text-sm text-stone-500">
                显示第 {filteredAccounts.length === 0 ? 0 : startIndex + 1} -{" "}
                {Math.min(startIndex + Number(pageSize), filteredAccounts.length)} 条，共{" "}
                {filteredAccounts.length} 条
                </div>

                <span className="shrink-0 text-sm leading-none text-stone-500">
                  {safePage} / {pageCount} 页
                </span>
                <Select
                  value={pageSize}
                  onValueChange={(value) => {
                    setPageSize(value);
                    setPage(1);
                  }}
                >
                  <SelectTrigger className="h-10 w-[108px] shrink-0 rounded-lg border-stone-200 bg-white text-sm leading-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10 / 页</SelectItem>
                    <SelectItem value="20">20 / 页</SelectItem>
                    <SelectItem value="50">50 / 页</SelectItem>
                    <SelectItem value="100">100 / 页</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  <ChevronLeft className="size-4" />
                </Button>
                {paginationItems.map((item, index) =>
                  item === "..." ? (
                    <span key={`ellipsis-${index}`} className="px-1 text-sm text-stone-400">
                      ...
                    </span>
                  ) : (
                    <Button
                      key={item}
                      variant={item === safePage ? "default" : "outline"}
                      className={cn(
                        "h-10 min-w-10 shrink-0 rounded-lg px-3",
                        item === safePage
                          ? "bg-stone-950 text-white hover:bg-stone-800"
                          : "border-stone-200 bg-white text-stone-700",
                      )}
                      onClick={() => setPage(item)}
                    >
                      {item}
                    </Button>
                  ),
                )}
                <Button
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-lg border-stone-200 bg-white"
                  disabled={safePage >= pageCount}
                  onClick={() => setPage((prev) => Math.min(pageCount, prev + 1))}
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <div className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white">
              <KeyRound className="size-4" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">用户 Key</h2>
              <p className="text-sm text-stone-500">给普通使用方单独分配次数，并限制管理权限。</p>
            </div>
          </div>

          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => void loadUserKeys()}
            disabled={isLoadingUserKeys || isSubmittingUserKeys || isDeletingUserKeys || isUpdatingUserKey}
          >
            <RefreshCw className={cn("size-4", isLoadingUserKeys ? "animate-spin" : "")} />
            刷新用户 key
          </Button>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-1 p-4">
              <div className="text-xs text-stone-400">用户 key 总数</div>
              <div className="text-2xl font-semibold tracking-tight text-stone-900">{userKeySummary.total}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-1 p-4">
              <div className="text-xs text-stone-400">启用中</div>
              <div className="text-2xl font-semibold tracking-tight text-emerald-600">{userKeySummary.enabled}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-1 p-4">
              <div className="text-xs text-stone-400">停用中</div>
              <div className="text-2xl font-semibold tracking-tight text-stone-500">{userKeySummary.disabled}</div>
            </CardContent>
          </Card>
          <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-1 p-4">
              <div className="text-xs text-stone-400">总剩余次数</div>
              <div className="text-2xl font-semibold tracking-tight text-blue-500">{userKeySummary.quota}</div>
            </CardContent>
          </Card>
        </div>

        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_160px] xl:grid-cols-[minmax(0,1fr)_160px_160px_160px_200px]">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">前缀</label>
              <Input
                value={newUserKeyPrefix}
                onChange={(event) => setNewUserKeyPrefix(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
                placeholder="uk"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">数量</label>
              <Input
                type="number"
                min="1"
                max="100"
                value={newUserKeyCount}
                onChange={(event) => setNewUserKeyCount(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">初始次数</label>
              <Input
                type="number"
                min="0"
                value={newUserKeyQuota}
                onChange={(event) => setNewUserKeyQuota(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">标签前缀</label>
              <Input
                value={newUserKeyLabelPrefix}
                onChange={(event) => setNewUserKeyLabelPrefix(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
                placeholder="例如 渠道A-"
              />
            </div>
            <div className="flex items-end">
              <Button
                className="h-11 w-full rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                onClick={() => void handleCreateUserKeys()}
                disabled={isSubmittingUserKeys}
              >
                {isSubmittingUserKeys ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
                批量生成
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="space-y-0 p-0">
            <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-semibold tracking-tight">Key 列表</h3>
                <Badge variant="secondary" className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700">
                  {filteredUserKeys.length}
                </Badge>
              </div>
              <div className="relative min-w-[260px]">
                <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
                <Input
                  value={userKeyQuery}
                  onChange={(event) => setUserKeyQuery(event.target.value)}
                  placeholder="搜索 key 或标签"
                  className="h-10 rounded-xl border-stone-200 bg-white/85 pl-10"
                />
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[880px] text-left">
                <thead className="border-b border-stone-100 text-[11px] text-stone-400 uppercase tracking-[0.18em]">
                  <tr>
                    <th className="w-56 px-4 py-3">key</th>
                    <th className="w-36 px-4 py-3">标签</th>
                    <th className="w-24 px-4 py-3">状态</th>
                    <th className="w-24 px-4 py-3">次数</th>
                    <th className="w-40 px-4 py-3">创建时间</th>
                    <th className="w-40 px-4 py-3">最近使用</th>
                    <th className="w-28 px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUserKeys.map((item) => (
                    <tr
                      key={item.id}
                      className="border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-medium tracking-tight text-stone-700">{maskToken(item.key)}</span>
                          <button
                            type="button"
                            className="rounded-lg p-1 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                            onClick={() => {
                              void navigator.clipboard.writeText(item.key);
                              toast.success("用户 key 已复制");
                            }}
                          >
                            <Copy className="size-4" />
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-stone-500">{item.label || "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant={item.status === "启用" ? "success" : "secondary"} className="rounded-md">
                          {item.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="info" className="rounded-md">
                          {formatQuota(item.quota)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-xs text-stone-500">{formatDateTime(item.createdAt)}</td>
                      <td className="px-4 py-3 text-xs text-stone-500">{formatDateTime(item.lastUsedAt)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1 text-stone-400">
                          <button
                            type="button"
                            className="rounded-lg p-2 transition hover:bg-stone-100 hover:text-stone-700"
                            onClick={() => openUserKeyDialog(item)}
                            disabled={isUpdatingUserKey}
                          >
                            <Pencil className="size-4" />
                          </button>
                          <button
                            type="button"
                            className="rounded-lg p-2 transition hover:bg-rose-50 hover:text-rose-500"
                            onClick={() => void handleDeleteUserKey(item.key)}
                            disabled={isDeletingUserKeys}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {!isLoadingUserKeys && filteredUserKeys.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <KeyRound className="size-5" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">还没有用户 key</p>
                    <p className="text-sm text-stone-500">先设好前缀、数量和初始次数，再批量生成。</p>
                  </div>
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </section>
    </>
  );
}
