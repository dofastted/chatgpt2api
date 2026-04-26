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
  Database,
  FileSearch,
  Download,
  HardDrive,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Save,
  Ticket,
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
import {
  cleanJsonText,
  extractAccountsFromJson,
  normalizeTokenList,
} from "@/lib/account-import";
import {
  createAccounts,
  createRedeemCodes,
  createDataBackup,
  createUserKeys,
  deleteProxy,
  deleteAccounts,
  deleteRedeemCodes,
  deleteUserKeys,
  fetchAuthSession,
  fetchAccounts,
  fetchDataBackups,
  fetchDataManagementLogs,
  fetchDataManagementSettings,
  fetchDataManagementStatus,
  fetchImageRequests,
  fetchProxies,
  fetchRedeemCodes,
  fetchUserKeys,
  refreshAccounts,
  testDataManagementS3,
  upsertProxy,
  updateDataManagementSettings,
  updateAccount,
  updateUserKey,
  type Account,
  type AccountCategory,
  type AccountStatus,
  type AccountType,
  type DataBackupRecord,
  type DataManagementLogItem,
  type DataManagementSettings,
  type DataManagementStatus,
  type ImageRequestRecord,
  type ImageRequestStatus,
  type ProxyItem,
  type ProxyProtocol,
  type RedeemCode,
  type UserKey,
  type UserKeyPricing,
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

const accountStatusOptions: { label: string; value: AccountStatus | "all" }[] =
  [
    { label: "全部状态", value: "all" },
    { label: "正常", value: "正常" },
    { label: "限流", value: "限流" },
    { label: "异常", value: "异常" },
    { label: "禁用", value: "禁用" },
  ];

const accountCategoryOptions: {
  label: string;
  value: AccountCategory | "all";
}[] = [
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
  {
    key: "active",
    label: "正常账户",
    color: "text-emerald-600",
    icon: CheckCircle2,
  },
  {
    key: "limited",
    label: "限流账户",
    color: "text-orange-500",
    icon: CircleAlert,
  },
  {
    key: "abnormal",
    label: "异常账户",
    color: "text-rose-500",
    icon: CircleOff,
  },
  { key: "disabled", label: "禁用账户", color: "text-stone-500", icon: Ban },
  { key: "quota", label: "剩余额度", color: "text-blue-500", icon: RefreshCw },
] as const;

const DEFAULT_USER_KEY_PRICING: UserKeyPricing = {
  "gpt-image-2": 2,
  "gpt-image-2-2K": 2,
  "gpt-image-2-4K": 8,
};

const imageModels: ImageModel[] = ["gpt-image-2", "gpt-image-2-2K", "gpt-image-2-4K"];

const ADMIN_SECONDARY_PAGE_SIZE = 10;

type AdminTab = "accounts" | "userKeys" | "redeemCodes" | "data";
type UserKeyExportState = {
  open: boolean;
  title: string;
  keys: string[];
  filenamePrefix: string;
};

const proxyProtocolOptions: Array<{ label: string; value: ProxyProtocol }> = [
  { label: "HTTP", value: "http" },
  { label: "SOCKS5", value: "socks5" },
];

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
  return formatCompact(
    accounts.reduce((sum, account) => sum + Math.max(0, account.quota), 0),
  );
}

function formatUserKeyQuotaSummary(userKeys: UserKey[]) {
  return formatCompact(
    userKeys.reduce((sum, item) => sum + Math.max(0, item.quota), 0),
  );
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

function formatBytes(value: number) {
  const bytes = Math.max(0, Number(value || 0));
  if (bytes >= 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function formatDurationMs(value?: number | null) {
  const ms = Math.max(0, Number(value || 0));
  if (!ms) {
    return "—";
  }
  if (ms < 1000) {
    return `${ms}ms`;
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

function buildUserKeyPricing(
  gptImage2: string,
  gptImage2K: string,
  gptImage4K: string,
): UserKeyPricing {
  return {
    "gpt-image-2": Math.max(0, Number(gptImage2 || 0)),
    "gpt-image-2-2K": Math.max(0, Number(gptImage2K || 0)),
    "gpt-image-2-4K": Math.max(0, Number(gptImage4K || 0)),
  };
}

function formatUserKeyPricing(pricing?: UserKeyPricing | null) {
  const resolved = { ...DEFAULT_USER_KEY_PRICING, ...(pricing || {}) };
  return [
    `gpt-image-2: ${formatQuota(resolved["gpt-image-2"])}`,
    `2K: ${formatQuota(resolved["gpt-image-2-2K"])}`,
    `4K: ${formatQuota(resolved["gpt-image-2-4K"])}`,
  ].join(" / ");
}

function maskToken(token?: string, visibleStart = 16, visibleEnd = 8) {
  if (!token) return "—";
  if (token.length <= visibleStart + visibleEnd) return token;
  return `${token.slice(0, visibleStart)}...${token.slice(-visibleEnd)}`;
}

function downloadTextFile(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 0);
}

function downloadTokens(accounts: Account[]) {
  const content = `${accounts.map((account) => account.access_token).join("\n")}\n`;
  downloadTextFile(content, `accounts-${Date.now()}.txt`);
}

function downloadRedeemCodes(
  codes: RedeemCode[],
  filenamePrefix = "redeem-codes",
) {
  if (codes.length === 0) {
    toast.error("没有可下载的兑换码");
    return;
  }
  const content = `${codes.map((item) => item.code).join("\n")}\n`;
  downloadTextFile(content, `${filenamePrefix}-${Date.now()}.txt`);
}

function downloadUserKeys(
  userKeys: UserKey[],
  filenamePrefix = "user-keys",
) {
  if (userKeys.length === 0) {
    toast.error("没有可下载的用户 key");
    return;
  }
  const content = `${userKeys.map((item) => item.key).join("\n")}\n`;
  downloadTextFile(content, `${filenamePrefix}-${Date.now()}.txt`);
}

function normalizeAccounts(items: Account[]): Account[] {
  return items.map((item) => ({
    ...item,
    category: item.category === "捐赠" ? "捐赠" : "普通",
    type:
      item.type === "Plus" ||
      item.type === "Team" ||
      item.type === "Pro" ||
      item.type === "Free"
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
  const [redeemCodes, setRedeemCodes] = useState<RedeemCode[]>([]);
  const [proxies, setProxies] = useState<ProxyItem[]>([]);
  const [activeProxyUrl, setActiveProxyUrl] = useState<string>("");
  const [dataStatus, setDataStatus] = useState<DataManagementStatus | null>(null);
  const [dataSettings, setDataSettings] = useState<DataManagementSettings | null>(null);
  const [dataBackups, setDataBackups] = useState<DataBackupRecord[]>([]);
  const [dataLogs, setDataLogs] = useState<DataManagementLogItem[]>([]);
  const [imageRequests, setImageRequests] = useState<ImageRequestRecord[]>([]);
  const [selectedImageRequest, setSelectedImageRequest] = useState<ImageRequestRecord | null>(null);
  const [imageRequestQuery, setImageRequestQuery] = useState("");
  const [imageRequestStatusFilter, setImageRequestStatusFilter] = useState<ImageRequestStatus | "all">("all");
  const [imageRequestModelFilter, setImageRequestModelFilter] = useState<ImageModel | "all">("all");
  const [imageRequestEndpointFilter, setImageRequestEndpointFilter] = useState<string>("all");
  const [activeTab, setActiveTab] = useState<AdminTab>("accounts");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedUserKeyIds, setSelectedUserKeyIds] = useState<string[]>([]);
  const [selectedRedeemCodeIds, setSelectedRedeemCodeIds] = useState<string[]>(
    [],
  );
  const [query, setQuery] = useState("");
  const [userKeyQuery, setUserKeyQuery] = useState("");
  const [redeemCodeQuery, setRedeemCodeQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<AccountCategory | "all">(
    "all",
  );
  const [typeFilter, setTypeFilter] = useState<AccountType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<AccountStatus | "all">(
    "all",
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState("10");
  const [userKeyPage, setUserKeyPage] = useState(1);
  const [redeemCodePage, setRedeemCodePage] = useState(1);
  const [open, setOpen] = useState(false);
  const [newTokens, setNewTokens] = useState("");
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);
  const [editingUserKey, setEditingUserKey] = useState<UserKey | null>(null);
  const [bulkEditUserKeysOpen, setBulkEditUserKeysOpen] = useState(false);
  const [editCategory, setEditCategory] = useState<AccountCategory>("普通");
  const [editType, setEditType] = useState<AccountType>("Free");
  const [editStatus, setEditStatus] = useState<AccountStatus>("正常");
  const [editQuota, setEditQuota] = useState("0");
  const [newUserKeyPrefix, setNewUserKeyPrefix] = useState("uk");
  const [newUserKeyLabelPrefix, setNewUserKeyLabelPrefix] = useState("");
  const [newUserKeyCount, setNewUserKeyCount] = useState("5");
  const [newUserKeyQuota, setNewUserKeyQuota] = useState("20");
  const [newUserKeyPriceImage2, setNewUserKeyPriceImage2] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2"]),
  );
  const [newUserKeyPriceImage2K, setNewUserKeyPriceImage2K] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2-2K"]),
  );
  const [newUserKeyPriceImage4K, setNewUserKeyPriceImage4K] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2-4K"]),
  );
  const [editUserKeyLabel, setEditUserKeyLabel] = useState("");
  const [editUserKeyQuota, setEditUserKeyQuota] = useState("0");
  const [editUserKeyLdcBalance, setEditUserKeyLdcBalance] = useState("0");
  const [editUserKeyStatus, setEditUserKeyStatus] =
    useState<UserKeyStatus>("启用");
  const [editUserKeyPriceImage2, setEditUserKeyPriceImage2] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2"]),
  );
  const [editUserKeyPriceImage2K, setEditUserKeyPriceImage2K] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2-2K"]),
  );
  const [editUserKeyPriceImage4K, setEditUserKeyPriceImage4K] = useState(
    String(DEFAULT_USER_KEY_PRICING["gpt-image-2-4K"]),
  );
  const [batchEditUserKeyQuota, setBatchEditUserKeyQuota] = useState("");
  const [batchEditUserKeyLdcBalance, setBatchEditUserKeyLdcBalance] =
    useState("");
  const [batchEditUserKeyStatus, setBatchEditUserKeyStatus] = useState<
    "unchanged" | UserKeyStatus
  >("unchanged");
  const [batchEditUserKeyPriceImage2, setBatchEditUserKeyPriceImage2] =
    useState("");
  const [batchEditUserKeyPriceImage2K, setBatchEditUserKeyPriceImage2K] =
    useState("");
  const [batchEditUserKeyPriceImage4K, setBatchEditUserKeyPriceImage4K] =
    useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isUploadingJson, setIsUploadingJson] = useState(false);
  const [isLoadingUserKeys, setIsLoadingUserKeys] = useState(true);
  const [isLoadingRedeemCodes, setIsLoadingRedeemCodes] = useState(true);
  const [isLoadingDataManagement, setIsLoadingDataManagement] = useState(true);
  const [isLoadingImageRequests, setIsLoadingImageRequests] = useState(true);
  const [isSavingDataSettings, setIsSavingDataSettings] = useState(false);
  const [isCreatingBackup, setIsCreatingBackup] = useState(false);
  const [isTestingS3, setIsTestingS3] = useState(false);
  const [isSubmittingUserKeys, setIsSubmittingUserKeys] = useState(false);
  const [isSubmittingRedeemCodes, setIsSubmittingRedeemCodes] = useState(false);
  const [isDeletingUserKeys, setIsDeletingUserKeys] = useState(false);
  const [isDeletingRedeemCodes, setIsDeletingRedeemCodes] = useState(false);
  const [isUpdatingUserKey, setIsUpdatingUserKey] = useState(false);
  const [isAuthorizing, setIsAuthorizing] = useState(true);
  const [newRedeemCodePrefix, setNewRedeemCodePrefix] = useState("RDM");
  const [newRedeemCodeCount, setNewRedeemCodeCount] = useState("5");
  const [newRedeemCodeTargetQuota, setNewRedeemCodeTargetQuota] = useState<
    "20" | "100"
  >("20");
  const [newRedeemCodeLabel, setNewRedeemCodeLabel] = useState("");
  const [lastCreatedUserKeys, setLastCreatedUserKeys] = useState<UserKey[]>(
    [],
  );
  const [userKeyExport, setUserKeyExport] = useState<UserKeyExportState>({
    open: false,
    title: "用户 key 下载",
    keys: [],
    filenamePrefix: "user-keys",
  });
  const [lastCreatedRedeemCodes, setLastCreatedRedeemCodes] = useState<
    RedeemCode[]
  >([]);
  const [proxyName, setProxyName] = useState("");
  const [proxyProtocol, setProxyProtocol] = useState<ProxyProtocol>("socks5");
  const [proxyHost, setProxyHost] = useState("");
  const [proxyPort, setProxyPort] = useState("");
  const [proxyUsername, setProxyUsername] = useState("");
  const [proxyPassword, setProxyPassword] = useState("");
  const [editingProxyId, setEditingProxyId] = useState<string | null>(null);

  function handleAdminRouteFailure(message: string) {
    const normalizedMessage = String(message || "").toLowerCase();
    if (normalizedMessage.includes("authorization is invalid")) {
      router.replace("/login");
      return true;
    }
    if (normalizedMessage.includes("admin authorization is required")) {
      toast.error("当前密钥没有号池管理权限");
      router.replace("/image");
      return true;
    }
    return false;
  }

  async function loadAccounts(silent = false) {
    if (!silent) {
      setIsLoading(true);
    }
    try {
      const data = await fetchAccounts({ redirectOnUnauthorized: false });
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载账户失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setIsLoading(false);
      }
    }
  }

  async function loadUserKeys(silent = false) {
    if (!silent) {
      setIsLoadingUserKeys(true);
    }
    try {
      const data = await fetchUserKeys({ redirectOnUnauthorized: false });
      setUserKeys(data.items);
      setSelectedUserKeyIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "加载用户 key 失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setIsLoadingUserKeys(false);
      }
    }
  }

  async function loadRedeemCodes(silent = false) {
    if (!silent) {
      setIsLoadingRedeemCodes(true);
    }
    try {
      const data = await fetchRedeemCodes({ redirectOnUnauthorized: false });
      setRedeemCodes(data.items);
      setSelectedRedeemCodeIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载兑换码失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setIsLoadingRedeemCodes(false);
      }
    }
  }

  async function loadProxies(silent = false) {
    try {
      const data = await fetchProxies({ redirectOnUnauthorized: false });
      setProxies(data.items);
      setActiveProxyUrl(String(data.active_proxy_url || ""));
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载代理失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    }
  }

  async function loadDataManagement(silent = false) {
    if (!silent) {
      setIsLoadingDataManagement(true);
    }
    try {
      const [status, settings, backups, logs] = await Promise.all([
        fetchDataManagementStatus({ redirectOnUnauthorized: false }),
        fetchDataManagementSettings({ redirectOnUnauthorized: false }),
        fetchDataBackups(),
        fetchDataManagementLogs(),
      ]);
      setDataStatus(status);
      setDataSettings(settings);
      setDataBackups(backups.items);
      setDataLogs(logs.items);
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载数据管理失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setIsLoadingDataManagement(false);
      }
    }
  }

  async function loadImageRequests(silent = false) {
    if (!silent) {
      setIsLoadingImageRequests(true);
    }
    try {
      const data = await fetchImageRequests({
        limit: 80,
        ...(imageRequestQuery.trim() ? { request_id: imageRequestQuery.trim() } : {}),
        ...(imageRequestStatusFilter !== "all" ? { status: imageRequestStatusFilter } : {}),
        ...(imageRequestModelFilter !== "all" ? { model: imageRequestModelFilter } : {}),
        ...(imageRequestEndpointFilter !== "all" ? { endpoint: imageRequestEndpointFilter } : {}),
      });
      setImageRequests(data.items);
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载请求记录失败";
      if (!handleAdminRouteFailure(message)) {
        toast.error(message);
      }
    } finally {
      if (!silent) {
        setIsLoadingImageRequests(false);
      }
    }
  }

  useEffect(() => {
    if (didLoadRef.current) {
      return;
    }
    didLoadRef.current = true;

    let cancelled = false;
    const bootstrap = async () => {
      try {
        const session = await fetchAuthSession({
          redirectOnUnauthorized: false,
          retries: 1,
        });
        if (cancelled) {
          return;
        }
        if (session.role !== "admin") {
          toast.error("当前密钥没有号池管理权限");
          router.replace("/image");
          return;
        }
        setIsAuthorizing(false);
        await Promise.all([
          loadAccounts(),
          loadUserKeys(),
          loadRedeemCodes(),
          loadProxies(),
          loadDataManagement(),
          loadImageRequests(),
        ]);
      } catch (error) {
        if (cancelled) {
          return;
        }
        const message =
          error instanceof Error ? error.message : "加载管理员会话失败";
        if (handleAdminRouteFailure(message)) {
          return;
        }
        setIsAuthorizing(false);
        toast.error(`加载管理员会话失败：${message}`);
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
        normalizedQuery.length === 0 ||
        (account.email ?? "").toLowerCase().includes(normalizedQuery);
      const categoryMatched =
        categoryFilter === "all" || account.category === categoryFilter;
      const typeMatched = typeFilter === "all" || account.type === typeFilter;
      const statusMatched =
        statusFilter === "all" || account.status === statusFilter;
      return searchMatched && categoryMatched && typeMatched && statusMatched;
    });
  }, [accounts, categoryFilter, query, statusFilter, typeFilter]);

  const pageCount = Math.max(
    1,
    Math.ceil(filteredAccounts.length / Number(pageSize)),
  );
  const safePage = Math.min(page, pageCount);
  const startIndex = (safePage - 1) * Number(pageSize);
  const currentRows = filteredAccounts.slice(
    startIndex,
    startIndex + Number(pageSize),
  );
  const allCurrentSelected =
    currentRows.length > 0 &&
    currentRows.every((row) => selectedIds.includes(row.id));

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
    return accounts
      .filter((item) => selectedSet.has(item.id))
      .map((item) => item.access_token);
  }, [accounts, selectedIds]);

  const abnormalTokens = useMemo(() => {
    return accounts
      .filter((item) => item.status === "异常")
      .map((item) => item.access_token);
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

  const filteredRedeemCodes = useMemo(() => {
    const normalizedQuery = redeemCodeQuery.trim().toLowerCase();
    return redeemCodes.filter((item) => {
      if (normalizedQuery.length === 0) {
        return true;
      }
      return (
        item.code.toLowerCase().includes(normalizedQuery) ||
        String(item.label || "")
          .toLowerCase()
          .includes(normalizedQuery)
      );
    });
  }, [redeemCodeQuery, redeemCodes]);

  const userKeyPageCount = Math.max(
    1,
    Math.ceil(filteredUserKeys.length / ADMIN_SECONDARY_PAGE_SIZE),
  );
  const safeUserKeyPage = Math.min(userKeyPage, userKeyPageCount);
  const userKeyStartIndex = (safeUserKeyPage - 1) * ADMIN_SECONDARY_PAGE_SIZE;
  const currentUserKeys = filteredUserKeys.slice(
    userKeyStartIndex,
    userKeyStartIndex + ADMIN_SECONDARY_PAGE_SIZE,
  );
  const selectedUserKeys = useMemo(() => {
    const selectedSet = new Set(selectedUserKeyIds);
    return userKeys.filter((item) => selectedSet.has(item.id));
  }, [selectedUserKeyIds, userKeys]);
  const allCurrentUserKeysSelected =
    currentUserKeys.length > 0 &&
    currentUserKeys.every((item) => selectedUserKeyIds.includes(item.id));
  const selectedRedeemCodes = useMemo(() => {
    const selectedSet = new Set(selectedRedeemCodeIds);
    return redeemCodes.filter((item) => selectedSet.has(item.id));
  }, [selectedRedeemCodeIds, redeemCodes]);
  const redeemCodePageCount = Math.max(
    1,
    Math.ceil(filteredRedeemCodes.length / ADMIN_SECONDARY_PAGE_SIZE),
  );
  const safeRedeemCodePage = Math.min(redeemCodePage, redeemCodePageCount);
  const redeemCodeStartIndex =
    (safeRedeemCodePage - 1) * ADMIN_SECONDARY_PAGE_SIZE;
  const currentRedeemCodes = filteredRedeemCodes.slice(
    redeemCodeStartIndex,
    redeemCodeStartIndex + ADMIN_SECONDARY_PAGE_SIZE,
  );
  const allCurrentRedeemCodesSelected =
    currentRedeemCodes.length > 0 &&
    currentRedeemCodes.every((item) => selectedRedeemCodeIds.includes(item.id));
  const usedRedeemCodes = useMemo(
    () => redeemCodes.filter((item) => item.status === "已使用"),
    [redeemCodes],
  );

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
      <div className="minimal-page-shell grid min-h-[calc(100vh-6rem)] place-items-center">
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
      const data = await createAccounts({ tokens });
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
        toast.success(
          `新增 ${data.added ?? 0} 个账户，跳过 ${data.skipped ?? 0} 个重复项，已自动刷新账号信息`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "新增账户失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const resetProxyEditor = () => {
    setEditingProxyId(null);
    setProxyName("");
    setProxyProtocol("socks5");
    setProxyHost("");
    setProxyPort("");
    setProxyUsername("");
    setProxyPassword("");
  };

  const handleSaveProxy = async () => {
    if (!proxyHost.trim() || !proxyPort.trim()) {
      toast.error("请先填写代理地址和端口");
      return;
    }
    setIsSubmitting(true);
    try {
      const data = await upsertProxy({
        id: editingProxyId || undefined,
        name: proxyName.trim() || undefined,
        protocol: proxyProtocol,
        host: proxyHost.trim(),
        port: Math.max(1, Number(proxyPort || 0)),
        username: proxyUsername.trim() || undefined,
        password: proxyPassword.trim() || undefined,
        enabled: true,
      });
      setProxies(data.items);
      setActiveProxyUrl(String(data.active_proxy_url || ""));
      resetProxyEditor();
      toast.success(editingProxyId ? "代理已更新" : "代理已保存并启用");
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存代理失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEditProxy = (item: ProxyItem) => {
    setEditingProxyId(item.id);
    setProxyName(String(item.name || ""));
    setProxyProtocol(item.protocol);
    setProxyHost(String(item.host || ""));
    setProxyPort(String(item.port || ""));
    setProxyUsername(String(item.username || ""));
    setProxyPassword(String(item.password || ""));
  };

  const handleEnableProxy = async (item: ProxyItem) => {
    setIsSubmitting(true);
    try {
      const data = await upsertProxy({
        id: item.id,
        name: item.name,
        protocol: item.protocol,
        host: item.host,
        port: item.port,
        username: String(item.username || "") || undefined,
        password: String(item.password || "") || undefined,
        enabled: true,
      });
      setProxies(data.items);
      setActiveProxyUrl(String(data.active_proxy_url || ""));
      toast.success("已切换代理出口");
    } catch (error) {
      const message = error instanceof Error ? error.message : "切换代理失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteProxy = async (id: string) => {
    setIsSubmitting(true);
    try {
      const data = await deleteProxy(id);
      setProxies(data.items);
      setActiveProxyUrl(String(data.active_proxy_url || ""));
      if (editingProxyId === id) {
        resetProxyEditor();
      }
      toast.success("代理已删除");
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除代理失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUploadJsonAccounts = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    setIsUploadingJson(true);

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

      const data = await createAccounts({ accounts: accountsToImport });
      setAccounts(normalizeAccounts(data.items));
      setSelectedIds([]);
      setNewTokens("");
      setPage(1);
      setOpen(false);

      const messages = [
        `已从 ${matchedFiles} 个文件导入 ${accountsToImport.length} 个账户`,
      ];
      if ((data.updated ?? 0) > 0) {
        messages.push(`覆盖 ${data.updated} 个已有账户`);
      }
      if ((data.skipped ?? 0) > 0) {
        messages.push(`跳过 ${data.skipped} 个无效或重复项`);
      }
      if ((data.errors?.length ?? 0) > 0) {
        messages.push(`刷新失败 ${data.errors?.length ?? 0} 个`);
      }
      if (invalidFiles.length > 0) {
        messages.push(`${invalidFiles.length} 个文件不是有效 JSON`);
      }
      if (emptyFiles.length > 0) {
        messages.push(`${emptyFiles.length} 个文件没有可识别的 token 字段`);
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
      setSelectedIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
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
      setSelectedIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
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
      setSelectedIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
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
    setEditUserKeyLdcBalance(String(userKey.ldcBalance || 0));
    setEditUserKeyStatus(userKey.status);
    const pricing = { ...DEFAULT_USER_KEY_PRICING, ...(userKey.pricing || {}) };
    setEditUserKeyPriceImage2(String(pricing["gpt-image-2"]));
    setEditUserKeyPriceImage2K(String(pricing["gpt-image-2-2K"]));
    setEditUserKeyPriceImage4K(String(pricing["gpt-image-2-4K"]));
  };

  const openUserKeyExportDialog = (
    items: UserKey[],
    title: string,
    filenamePrefix: string,
    downloadNow = false,
  ) => {
    const keys = items.map((item) => String(item.key || "").trim()).filter(Boolean);
    if (keys.length === 0) {
      toast.error("没有可下载的用户 key");
      return;
    }
    setUserKeyExport({
      open: true,
      title,
      keys,
      filenamePrefix,
    });
    if (downloadNow) {
      downloadUserKeys(items, filenamePrefix);
    }
  };

  const handleCreateUserKeys = async () => {
    setIsSubmittingUserKeys(true);
    try {
      const data = await createUserKeys({
        count: Math.max(1, Number(newUserKeyCount || 1)),
        quota: Math.max(0, Number(newUserKeyQuota || 0)),
        prefix: newUserKeyPrefix.trim() || undefined,
        label_prefix: newUserKeyLabelPrefix.trim() || undefined,
        pricing: buildUserKeyPricing(
          newUserKeyPriceImage2,
          newUserKeyPriceImage2K,
          newUserKeyPriceImage4K,
        ),
      });
      setUserKeys(data.items);
      const createdItems = data.created_items ?? [];
      setLastCreatedUserKeys(createdItems);
      if (createdItems.length > 0) {
        openUserKeyExportDialog(
          createdItems,
          "本次生成的用户 key",
          "user-keys-latest",
          true,
        );
      }
      toast.success(
        `已生成 ${createdItems.length || data.added || 0} 个用户 key`,
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "生成用户 key 失败";
      toast.error(message);
    } finally {
      setIsSubmittingUserKeys(false);
    }
  };

  const handleDeleteUserKey = async (key: string) => {
    await handleDeleteUserKeys([key]);
  };

  const handleDeleteUserKeys = async (keys: string[]) => {
    if (keys.length === 0) {
      toast.error("请先选择要删除的用户 key");
      return;
    }
    setIsDeletingUserKeys(true);
    try {
      const data = await deleteUserKeys(keys);
      setUserKeys(data.items);
      setSelectedUserKeyIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
      setEditingUserKey((prev) =>
        prev && keys.includes(prev.key) ? null : prev,
      );
      toast.success(`已删除 ${data.removed ?? 0} 个用户 key`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "删除用户 key 失败";
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
        ldc_balance: Math.max(0, Number(editUserKeyLdcBalance || 0)),
        status: editUserKeyStatus,
        pricing: buildUserKeyPricing(
          editUserKeyPriceImage2,
          editUserKeyPriceImage2K,
          editUserKeyPriceImage4K,
        ),
      });
      setUserKeys(data.items);
      setEditingUserKey(null);
      toast.success("用户 key 已更新");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "更新用户 key 失败";
      toast.error(message);
    } finally {
      setIsUpdatingUserKey(false);
    }
  };

  const resetBatchUserKeyEditor = () => {
    setBatchEditUserKeyQuota("");
    setBatchEditUserKeyLdcBalance("");
    setBatchEditUserKeyStatus("unchanged");
    setBatchEditUserKeyPriceImage2("");
    setBatchEditUserKeyPriceImage2K("");
    setBatchEditUserKeyPriceImage4K("");
  };

  const handleBatchUpdateUserKeys = async () => {
    if (selectedUserKeys.length === 0) {
      toast.error("请先选择要批量编辑的用户 key");
      return;
    }

    const updates: {
      quota?: number;
      ldc_balance?: number;
      status?: UserKeyStatus;
    } = {};
    const pricingOverrides: Partial<UserKeyPricing> = {};

    if (batchEditUserKeyQuota.trim() !== "") {
      updates.quota = Math.max(0, Number(batchEditUserKeyQuota || 0));
    }
    if (batchEditUserKeyLdcBalance.trim() !== "") {
      updates.ldc_balance = Math.max(
        0,
        Number(batchEditUserKeyLdcBalance || 0),
      );
    }
    if (batchEditUserKeyStatus !== "unchanged") {
      updates.status = batchEditUserKeyStatus;
    }
    if (batchEditUserKeyPriceImage2.trim() !== "") {
      pricingOverrides["gpt-image-2"] = Math.max(0, Number(batchEditUserKeyPriceImage2 || 0));
    }
    if (batchEditUserKeyPriceImage2K.trim() !== "") {
      pricingOverrides["gpt-image-2-2K"] = Math.max(0, Number(batchEditUserKeyPriceImage2K || 0));
    }
    if (batchEditUserKeyPriceImage4K.trim() !== "") {
      pricingOverrides["gpt-image-2-4K"] = Math.max(0, Number(batchEditUserKeyPriceImage4K || 0));
    }

    if (Object.keys(updates).length === 0 && Object.keys(pricingOverrides).length === 0) {
      toast.error("请至少填写一项批量修改内容");
      return;
    }

    setIsUpdatingUserKey(true);
    try {
      await Promise.all(
        selectedUserKeys.map((item) =>
          updateUserKey(item.key, {
            ...updates,
            ...(Object.keys(pricingOverrides).length > 0
              ? {
                  pricing: {
                    ...DEFAULT_USER_KEY_PRICING,
                    ...(item.pricing || {}),
                    ...pricingOverrides,
                  },
                }
              : {}),
          }),
        ),
      );
      await loadUserKeys(true);
      setBulkEditUserKeysOpen(false);
      resetBatchUserKeyEditor();
      toast.success(`已批量更新 ${selectedUserKeys.length} 个用户 key`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "批量更新用户 key 失败";
      toast.error(message);
    } finally {
      setIsUpdatingUserKey(false);
    }
  };

  const handleCreateRedeemCodes = async () => {
    setIsSubmittingRedeemCodes(true);
    try {
      const data = await createRedeemCodes({
        count: Math.max(1, Number(newRedeemCodeCount || 1)),
        target_quota: Math.max(0, Number(newRedeemCodeTargetQuota || 0)),
        prefix: newRedeemCodePrefix.trim() || undefined,
        label: newRedeemCodeLabel.trim() || undefined,
      });
      setRedeemCodes(data.items);
      const createdItems = data.created_items ?? [];
      setLastCreatedRedeemCodes(createdItems);
      if (createdItems.length > 0) {
        downloadRedeemCodes(
          createdItems,
          `redeem-codes-${newRedeemCodeTargetQuota}`,
        );
      }
      toast.success(
        `已生成 ${createdItems.length || data.added || 0} 个兑换码`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "生成兑换码失败";
      toast.error(message);
    } finally {
      setIsSubmittingRedeemCodes(false);
    }
  };

  const handleDeleteRedeemCode = async (code: string) => {
    await handleDeleteRedeemCodes([code]);
  };

  const handleDeleteRedeemCodes = async (codes: string[]) => {
    if (codes.length === 0) {
      toast.error("请先选择要删除的兑换码");
      return;
    }
    setIsDeletingRedeemCodes(true);
    try {
      const data = await deleteRedeemCodes(codes);
      setRedeemCodes(data.items);
      setSelectedRedeemCodeIds((prev) =>
        prev.filter((id) => data.items.some((item) => item.id === id)),
      );
      setLastCreatedRedeemCodes((prev) =>
        prev.filter((item) =>
          data.items.some((current) => current.id === item.id),
        ),
      );
      toast.success(`已删除 ${data.removed ?? 0} 个兑换码`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除兑换码失败";
      toast.error(message);
    } finally {
      setIsDeletingRedeemCodes(false);
    }
  };

  const handleSaveDataSettings = async () => {
    if (!dataSettings) {
      return;
    }
    setIsSavingDataSettings(true);
    try {
      const saved = await updateDataManagementSettings(dataSettings);
      setDataSettings(saved);
      await loadDataManagement(true);
      toast.success("数据管理设置已保存");
    } catch (error) {
      const message = error instanceof Error ? error.message : "保存数据管理设置失败";
      toast.error(message);
    } finally {
      setIsSavingDataSettings(false);
    }
  };

  const handleCreateDataBackup = async () => {
    setIsCreatingBackup(true);
    try {
      const backup = await createDataBackup();
      await loadDataManagement(true);
      if (backup.status === "success") {
        toast.success("备份已创建");
      } else {
        toast.error(backup.error || "备份创建失败");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "创建备份失败";
      toast.error(message);
    } finally {
      setIsCreatingBackup(false);
    }
  };

  const handleTestDataS3 = async () => {
    if (!dataSettings) {
      return;
    }
    setIsTestingS3(true);
    try {
      await testDataManagementS3(dataSettings.s3);
      toast.success("S3 连接正常");
    } catch (error) {
      const message = error instanceof Error ? error.message : "S3 连接失败";
      toast.error(message);
    } finally {
      setIsTestingS3(false);
    }
  };

  const updateDataS3Field = (key: keyof DataManagementSettings["s3"], value: string | boolean) => {
    setDataSettings((prev) =>
      prev
        ? {
            ...prev,
            s3: {
              ...prev.s3,
              [key]: value,
            },
          }
        : prev,
    );
  };

  const toggleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) =>
        Array.from(new Set([...prev, ...currentRows.map((item) => item.id)])),
      );
      return;
    }
    setSelectedIds((prev) =>
      prev.filter((id) => !currentRows.some((row) => row.id === id)),
    );
  };

  const toggleSelectAllUserKeys = (checked: boolean) => {
    if (checked) {
      setSelectedUserKeyIds((prev) =>
        Array.from(
          new Set([...prev, ...currentUserKeys.map((item) => item.id)]),
        ),
      );
      return;
    }
    setSelectedUserKeyIds((prev) =>
      prev.filter((id) => !currentUserKeys.some((item) => item.id === id)),
    );
  };

  const toggleSelectAllRedeemCodes = (checked: boolean) => {
    if (checked) {
      setSelectedRedeemCodeIds((prev) =>
        Array.from(
          new Set([...prev, ...currentRedeemCodes.map((item) => item.id)]),
        ),
      );
      return;
    }
    setSelectedRedeemCodeIds((prev) =>
      prev.filter((id) => !currentRedeemCodes.some((item) => item.id === id)),
    );
  };

  const adminTabs: Array<{ value: AdminTab; label: string }> = [
    { value: "accounts", label: "账号池" },
    { value: "userKeys", label: "用户 Key" },
    { value: "redeemCodes", label: "兑换码" },
    { value: "data", label: "数据管理" },
  ];

  return (
    <div className="minimal-page-shell minimal-admin-shell minimal-fade-soft space-y-5">
      <section className="minimal-fade-up space-y-4">
        <div className="space-y-1">
          <div className="minimal-kicker">admin system</div>
          <h1 className="minimal-heading mt-3 text-4xl sm:text-5xl">
            管理后台
          </h1>
        </div>

        <div className="flex flex-wrap gap-2">
          {adminTabs.map((tab) => (
            <Button
              key={tab.value}
              variant={activeTab === tab.value ? "default" : "outline"}
              className={cn(
                "minimal-surface-hover h-10 rounded-xl px-4",
                activeTab === tab.value
                  ? "bg-stone-950 text-white hover:bg-stone-800"
                  : "border-stone-200 bg-white/80 text-stone-700 hover:bg-white",
              )}
              onClick={() => setActiveTab(tab.value)}
            >
              {tab.label}
            </Button>
          ))}
        </div>
      </section>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>新增账户</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              支持批量上传标准 JSON 或 CPA 格式 JSON，也支持手动粘贴 Access
              Token。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <input
              ref={uploadInputRef}
              type="file"
              accept=".json,application/json"
              multiple
              className="hidden"
              onChange={(event) =>
                void handleUploadJsonAccounts(
                  Array.from(event.target.files ?? []),
                )
              }
            />
            <div className="rounded-2xl border border-dashed border-stone-200 bg-stone-50/70 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-stone-800">
                    批量上传 JSON
                  </div>
                  <p className="text-xs leading-5 text-stone-500">
                    可多选文件。系统会自动识别
                    `access_token`、`accessToken`、`token`
                    等字段，然后直接调用新增接口。
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700 hover:bg-stone-100"
                  onClick={() => uploadInputRef.current?.click()}
                  disabled={isSubmitting || isUploadingJson}
                >
                  {isUploadingJson ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <Upload className="size-4" />
                  )}
                  上传 JSON
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">
                Token 列表
              </label>
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
              {isSubmitting ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : null}
              新增账户
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(editingAccount)}
        onOpenChange={(open) => (!open ? setEditingAccount(null) : null)}
      >
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
              <Select
                value={editCategory}
                onValueChange={(value) =>
                  setEditCategory(value as AccountCategory)
                }
              >
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
              <Select
                value={editStatus}
                onValueChange={(value) => setEditStatus(value as AccountStatus)}
              >
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
              <Select
                value={editType}
                onValueChange={(value) => setEditType(value as AccountType)}
              >
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
              {isUpdating ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(editingUserKey)}
        onOpenChange={(open) => (!open ? setEditingUserKey(null) : null)}
      >
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>编辑用户 key</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              手动修改标签、状态、剩余次数和模型单价。
            </DialogDescription>
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
              <Select
                value={editUserKeyStatus}
                onValueChange={(value) =>
                  setEditUserKeyStatus(value as UserKeyStatus)
                }
              >
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
              <label className="text-sm font-medium text-stone-700">
                剩余次数
              </label>
              <Input
                value={editUserKeyQuota}
                onChange={(event) => setEditUserKeyQuota(event.target.value)}
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">
                积分余额
              </label>
              <Input
                value={editUserKeyLdcBalance}
                onChange={(event) =>
                  setEditUserKeyLdcBalance(event.target.value)
                }
                className="h-11 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2 单价
                </label>
                <Input
                  value={editUserKeyPriceImage2}
                  onChange={(event) =>
                    setEditUserKeyPriceImage2(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-2K 单价
                </label>
                <Input
                  value={editUserKeyPriceImage2K}
                  onChange={(event) =>
                    setEditUserKeyPriceImage2K(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-4K 单价
                </label>
                <Input
                  value={editUserKeyPriceImage4K}
                  onChange={(event) =>
                    setEditUserKeyPriceImage4K(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
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
              {isUpdatingUserKey ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : null}
              保存修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={userKeyExport.open}
        onOpenChange={(open) =>
          setUserKeyExport((prev) => ({
            ...prev,
            open,
          }))
        }
      >
        <DialogContent showCloseButton={false} className="max-w-2xl rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>{userKeyExport.title}</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              共 {userKeyExport.keys.length} 个用户 key，一行一个。可直接下载 txt，也可复制全部。
            </DialogDescription>
          </DialogHeader>
          <Textarea
            readOnly
            value={`${userKeyExport.keys.join("\n")}\n`}
            className="min-h-72 resize-none rounded-xl border-stone-200 bg-stone-50 font-mono text-xs leading-5 text-stone-700"
          />
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => {
                void navigator.clipboard.writeText(
                  `${userKeyExport.keys.join("\n")}\n`,
                );
                toast.success("用户 key 已复制");
              }}
              disabled={userKeyExport.keys.length === 0}
            >
              <Copy className="size-4" />
              复制全部
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() =>
                downloadTextFile(
                  `${userKeyExport.keys.join("\n")}\n`,
                  `${userKeyExport.filenamePrefix}-${Date.now()}.txt`,
                )
              }
              disabled={userKeyExport.keys.length === 0}
            >
              <Download className="size-4" />
              下载 txt
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white px-5 text-stone-700 hover:bg-stone-100"
              onClick={() =>
                setUserKeyExport((prev) => ({
                  ...prev,
                  open: false,
                }))
              }
            >
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={bulkEditUserKeysOpen}
        onOpenChange={(open) => {
          setBulkEditUserKeysOpen(open);
          if (!open) {
            resetBatchUserKeyEditor();
          }
        }}
      >
        <DialogContent showCloseButton={false} className="rounded-2xl p-6">
          <DialogHeader className="gap-2">
            <DialogTitle>批量编辑用户 key</DialogTitle>
            <DialogDescription className="text-sm leading-6">
              当前已选择 {selectedUserKeys.length} 个用户
              key。留空的字段不会修改。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-700">状态</label>
              <Select
                value={batchEditUserKeyStatus}
                onValueChange={(value) =>
                  setBatchEditUserKeyStatus(
                    value as "unchanged" | UserKeyStatus,
                  )
                }
              >
                <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unchanged">不修改</SelectItem>
                  <SelectItem value="启用">启用</SelectItem>
                  <SelectItem value="停用">停用</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  剩余次数
                </label>
                <Input
                  value={batchEditUserKeyQuota}
                  onChange={(event) =>
                    setBatchEditUserKeyQuota(event.target.value)
                  }
                  placeholder="留空不改"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  积分余额
                </label>
                <Input
                  value={batchEditUserKeyLdcBalance}
                  onChange={(event) =>
                    setBatchEditUserKeyLdcBalance(event.target.value)
                  }
                  placeholder="留空不改"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2 单价
                </label>
                <Input
                  value={batchEditUserKeyPriceImage2}
                  onChange={(event) =>
                    setBatchEditUserKeyPriceImage2(event.target.value)
                  }
                  placeholder="留空不改"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-2K 单价
                </label>
                <Input
                  value={batchEditUserKeyPriceImage2K}
                  onChange={(event) =>
                    setBatchEditUserKeyPriceImage2K(event.target.value)
                  }
                  placeholder="留空不改"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-4K 单价
                </label>
                <Input
                  value={batchEditUserKeyPriceImage4K}
                  onChange={(event) =>
                    setBatchEditUserKeyPriceImage4K(event.target.value)
                  }
                  placeholder="留空不改"
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
          </div>
          <DialogFooter className="pt-2">
            <Button
              variant="secondary"
              className="h-10 rounded-xl bg-stone-100 px-5 text-stone-700 hover:bg-stone-200"
              onClick={() => setBulkEditUserKeysOpen(false)}
              disabled={isUpdatingUserKey}
            >
              取消
            </Button>
            <Button
              className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
              onClick={() => void handleBatchUpdateUserKeys()}
              disabled={isUpdatingUserKey || selectedUserKeys.length === 0}
            >
              {isUpdatingUserKey ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : null}
              保存批量修改
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {activeTab === "accounts" ? (
        <>
          <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-1">
              <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
                Account Pool
              </div>
              <h2 className="text-2xl font-semibold tracking-tight">
                号池管理
              </h2>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
                onClick={() => void loadAccounts()}
                disabled={
                  isLoading || isRefreshing || isSubmitting || isDeleting
                }
              >
                <RefreshCw
                  className={cn("size-4", isLoading ? "animate-spin" : "")}
                />
                刷新
              </Button>
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
                onClick={() =>
                  void handleRefreshAccounts(
                    accounts.map((item) => item.access_token),
                  )
                }
                disabled={
                  isLoading ||
                  isRefreshing ||
                  isSubmitting ||
                  isDeleting ||
                  accounts.length === 0
                }
              >
                <RefreshCw
                  className={cn("size-4", isRefreshing ? "animate-spin" : "")}
                />
                一键刷新所有账号信息和额度
              </Button>
              <Button
                className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                onClick={() => setOpen(true)}
              >
                <Plus className="size-4" />
                新增
              </Button>
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

          <section className="minimal-fade-soft space-y-3 [animation-delay:120ms]">
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
              {metricCards.map((item, index) => {
                const Icon = item.icon;
                const value = summary[item.key];
                return (
                  <Card
                    key={item.key}
                    className={cn(
                      "minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm",
                      index === 0
                        ? "[animation-delay:80ms]"
                        : index === 1
                          ? "[animation-delay:120ms]"
                          : index === 2
                            ? "[animation-delay:160ms]"
                            : index === 3
                              ? "[animation-delay:200ms]"
                              : index === 4
                                ? "[animation-delay:240ms]"
                                : "[animation-delay:280ms]",
                    )}
                  >
                    <CardContent className="p-4">
                      <div className="mb-4 flex items-start justify-between">
                        <span className="text-xs font-medium text-stone-400">
                          {item.label}
                        </span>
                        <Icon className="size-4 text-stone-400" />
                      </div>
                      <div
                        className={cn(
                          "text-[1.75rem] font-semibold tracking-tight",
                          item.color,
                        )}
                      >
                        <span
                          className={
                            typeof value === "number" ? "" : "text-[1.1rem]"
                          }
                        >
                          {typeof value === "number"
                            ? formatCompact(value)
                            : value}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </section>

          <section className="minimal-fade-soft grid gap-4 xl:grid-cols-[minmax(0,1.8fr)_380px] [animation-delay:180ms]">
            <div className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-semibold tracking-tight">
                  账户列表
                </h2>
                <Badge
                  variant="secondary"
                  className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700"
                >
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
              <Card className="minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
                <CardContent className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
                  <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                    <LoaderCircle className="size-5 animate-spin" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-stone-700">
                      正在加载账户
                    </p>
                    <p className="text-sm text-stone-500">
                      从后端同步账号列表和状态。
                    </p>
                  </div>
                </CardContent>
              </Card>
            ) : null}

            <Card
              className={cn(
                "minimal-surface-hover overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm",
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
                      {isRefreshing ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <RefreshCw className="size-4" />
                      )}
                      刷新选中账号信息和额度
                    </Button>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                      onClick={() => void handleDeleteTokens(abnormalTokens)}
                      disabled={abnormalTokens.length === 0 || isDeleting}
                    >
                      {isDeleting ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4" />
                      )}
                      移除异常账号
                    </Button>
                    <Button
                      variant="ghost"
                      className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                      onClick={() => void handleDeleteTokens(selectedTokens)}
                      disabled={selectedTokens.length === 0 || isDeleting}
                    >
                      {isDeleting ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <Trash2 className="size-4" />
                      )}
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
                            onCheckedChange={(checked) =>
                              toggleSelectAll(Boolean(checked))
                            }
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
                            className="minimal-row-shift border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70"
                          >
                            <td className="px-4 py-3">
                              <Checkbox
                                checked={selectedIds.includes(account.id)}
                                onCheckedChange={(checked) => {
                                  setSelectedIds((prev) =>
                                    checked
                                      ? Array.from(
                                          new Set([...prev, account.id]),
                                        )
                                      : prev.filter(
                                          (item) => item !== account.id,
                                        ),
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
                                    void navigator.clipboard.writeText(
                                      account.access_token,
                                    );
                                    toast.success("token 已复制");
                                  }}
                                >
                                  <Copy className="size-4" />
                                </button>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <Badge
                                variant={
                                  account.category === "捐赠"
                                    ? "info"
                                    : "secondary"
                                }
                                className="rounded-md"
                              >
                                {account.category}
                              </Badge>
                            </td>
                            <td className="px-4 py-3">
                              <Badge
                                variant="secondary"
                                className="rounded-md bg-stone-100 text-stone-700"
                              >
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
                              <div className="text-xs leading-5 text-stone-500">
                                {account.email ?? "—"}
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <Badge variant="info" className="rounded-md">
                                {formatQuota(account.quota)}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-xs leading-5 text-stone-500">
                              {(() => {
                                const restore = formatRestoreAt(
                                  account.restoreAt,
                                );
                                return (
                                  <div className="space-y-0.5">
                                    {restore.relative ? (
                                      <div className="font-medium text-stone-700">
                                        {restore.relative}
                                      </div>
                                    ) : null}
                                    <div>{restore.absolute}</div>
                                  </div>
                                );
                              })()}
                            </td>
                            <td className="px-4 py-3 text-stone-500">
                              {account.success}
                            </td>
                            <td className="px-4 py-3 text-stone-500">
                              {account.fail}
                            </td>
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
                                  onClick={() =>
                                    void handleRefreshAccounts([
                                      account.access_token,
                                    ])
                                  }
                                  disabled={isRefreshing}
                                >
                                  <RefreshCw
                                    className={cn(
                                      "size-4",
                                      isRefreshing ? "animate-spin" : "",
                                    )}
                                  />
                                </button>
                                <button
                                  type="button"
                                  className="rounded-lg p-2 transition hover:bg-rose-50 hover:text-rose-500"
                                  onClick={() =>
                                    void handleDeleteTokens([
                                      account.access_token,
                                    ])
                                  }
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
                        <p className="text-sm font-medium text-stone-700">
                          没有匹配的账户
                        </p>
                        <p className="text-sm text-stone-500">
                          调整筛选条件或搜索关键字后重试。
                        </p>
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="border-t border-stone-100 px-4 py-4">
                  <div className="flex items-center justify-center gap-3 overflow-x-auto whitespace-nowrap">
                    <div className="shrink-0 text-sm text-stone-500">
                      显示第{" "}
                      {filteredAccounts.length === 0 ? 0 : startIndex + 1} -{" "}
                      {Math.min(
                        startIndex + Number(pageSize),
                        filteredAccounts.length,
                      )}{" "}
                      条，共 {filteredAccounts.length} 条
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
                        <span
                          key={`ellipsis-${index}`}
                          className="px-1 text-sm text-stone-400"
                        >
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
                      onClick={() =>
                        setPage((prev) => Math.min(pageCount, prev + 1))
                      }
                    >
                      <ChevronRight className="size-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
            </div>

            <Card className="minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="space-y-5 p-5">
                <div className="space-y-1">
                  <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
                    Proxy
                  </div>
                  <h3 className="text-xl font-semibold tracking-tight">
                    代理管理
                  </h3>
                  <p className="text-sm leading-6 text-stone-500">
                    所有账号刷新和生图请求都会优先走当前启用代理。没有启用代理时自动直连。
                  </p>
                </div>

                <div className="rounded-2xl border border-stone-200 bg-stone-50/80 p-4">
                  <div className="text-xs font-medium tracking-[0.18em] text-stone-400 uppercase">
                    当前出口
                  </div>
                  <div className="mt-2 break-all text-sm font-medium text-stone-700">
                    {activeProxyUrl || "直连"}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-stone-700">
                      名称
                    </label>
                    <Input
                      value={proxyName}
                      onChange={(event) => setProxyName(event.target.value)}
                      placeholder="例如：美国 01"
                      className="h-11 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-stone-700">
                        协议
                      </label>
                      <Select
                        value={proxyProtocol}
                        onValueChange={(value) =>
                          setProxyProtocol(value as ProxyProtocol)
                        }
                      >
                        <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {proxyProtocolOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-stone-700">
                        端口
                      </label>
                      <Input
                        value={proxyPort}
                        onChange={(event) => setProxyPort(event.target.value)}
                        placeholder="1080"
                        className="h-11 rounded-xl border-stone-200 bg-white"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-stone-700">
                      地址
                    </label>
                    <Input
                      value={proxyHost}
                      onChange={(event) => setProxyHost(event.target.value)}
                      placeholder="127.0.0.1"
                      className="h-11 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-stone-700">
                        用户名
                      </label>
                      <Input
                        value={proxyUsername}
                        onChange={(event) => setProxyUsername(event.target.value)}
                        placeholder="可留空"
                        className="h-11 rounded-xl border-stone-200 bg-white"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-stone-700">
                        密码
                      </label>
                      <Input
                        value={proxyPassword}
                        onChange={(event) => setProxyPassword(event.target.value)}
                        placeholder="可留空"
                        className="h-11 rounded-xl border-stone-200 bg-white"
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                      onClick={() => void handleSaveProxy()}
                      disabled={isSubmitting}
                    >
                      {isSubmitting ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : null}
                      {editingProxyId ? "保存并启用" : "新增并启用"}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700 hover:bg-stone-100"
                      onClick={resetProxyEditor}
                      disabled={isSubmitting}
                    >
                      清空
                    </Button>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium text-stone-700">
                      已保存节点
                    </div>
                    <Badge
                      variant="secondary"
                      className="rounded-lg bg-stone-100 text-stone-700"
                    >
                      {proxies.length}
                    </Badge>
                  </div>
                  <div className="space-y-3">
                    {proxies.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-stone-200 px-4 py-6 text-sm text-stone-500">
                        当前没有保存的代理，服务会走直连。
                      </div>
                    ) : (
                      proxies.map((item) => (
                        <div
                          key={item.id}
                          className="rounded-2xl border border-stone-200 bg-white p-4"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <div className="text-sm font-medium text-stone-800">
                                  {item.name}
                                </div>
                                {item.enabled ? (
                                  <Badge variant="success" className="rounded-md">
                                    已启用
                                  </Badge>
                                ) : null}
                              </div>
                              <div className="text-xs text-stone-500">
                                {item.protocol.toUpperCase()} · {item.host}:{item.port}
                              </div>
                              <div className="text-xs break-all text-stone-400">
                                {item.url || "—"}
                              </div>
                            </div>
                            <div className="flex items-center gap-1">
                              {!item.enabled ? (
                                <button
                                  type="button"
                                  className="rounded-lg p-2 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                                  onClick={() => void handleEnableProxy(item)}
                                  disabled={isSubmitting}
                                >
                                  <CheckCircle2 className="size-4" />
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="rounded-lg p-2 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                                onClick={() => handleEditProxy(item)}
                                disabled={isSubmitting}
                              >
                                <Pencil className="size-4" />
                              </button>
                              <button
                                type="button"
                                className="rounded-lg p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500"
                                onClick={() => void handleDeleteProxy(item.id)}
                                disabled={isSubmitting}
                              >
                                <Trash2 className="size-4" />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </section>
        </>
      ) : null}

      {activeTab === "userKeys" ? (
        <section className="minimal-fade-soft space-y-4 [animation-delay:180ms]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3">
              <div className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white">
                <KeyRound className="size-4" />
              </div>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">
                  用户 Key
                </h2>
                <p className="text-sm text-stone-500">
                  给普通使用方单独分配次数，并限制管理权限。
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() => void loadUserKeys()}
              disabled={
                isLoadingUserKeys ||
                isSubmittingUserKeys ||
                isDeletingUserKeys ||
                isUpdatingUserKey
              }
            >
              <RefreshCw
                className={cn(
                  "size-4",
                  isLoadingUserKeys ? "animate-spin" : "",
                )}
              />
              刷新用户 key
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() =>
                openUserKeyExportDialog(
                  lastCreatedUserKeys,
                  "本次生成的用户 key",
                  "user-keys-latest",
                )
              }
              disabled={lastCreatedUserKeys.length === 0}
            >
              <Download className="size-4" />
              下载本次 txt
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() =>
                openUserKeyExportDialog(
                  selectedUserKeys,
                  "所选用户 key",
                  "user-keys-selected",
                  true,
                )
              }
              disabled={selectedUserKeys.length === 0}
            >
              <Download className="size-4" />
              下载所选
            </Button>
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Card className="minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="space-y-1 p-4">
                <div className="text-xs text-stone-400">用户 key 总数</div>
                <div className="text-2xl font-semibold tracking-tight text-stone-900">
                  {userKeySummary.total}
                </div>
              </CardContent>
            </Card>
            <Card className="minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="space-y-1 p-4">
                <div className="text-xs text-stone-400">启用中</div>
                <div className="text-2xl font-semibold tracking-tight text-emerald-600">
                  {userKeySummary.enabled}
                </div>
              </CardContent>
            </Card>
            <Card className="minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="space-y-1 p-4">
                <div className="text-xs text-stone-400">停用中</div>
                <div className="text-2xl font-semibold tracking-tight text-stone-500">
                  {userKeySummary.disabled}
                </div>
              </CardContent>
            </Card>
            <Card className="minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
              <CardContent className="space-y-1 p-4">
                <div className="text-xs text-stone-400">总剩余次数</div>
                <div className="text-2xl font-semibold tracking-tight text-blue-500">
                  {userKeySummary.quota}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="minimal-fade-soft minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_140px_140px] xl:grid-cols-[minmax(0,1fr)_140px_140px_140px_160px_200px]">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  前缀
                </label>
                <Input
                  value={newUserKeyPrefix}
                  onChange={(event) => setNewUserKeyPrefix(event.target.value)}
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  placeholder="uk"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  数量
                </label>
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
                <label className="text-sm font-medium text-stone-700">
                  初始次数
                </label>
                <Input
                  type="number"
                  min="0"
                  value={newUserKeyQuota}
                  onChange={(event) => setNewUserKeyQuota(event.target.value)}
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2 单价
                </label>
                <Input
                  type="number"
                  min="0"
                  value={newUserKeyPriceImage2}
                  onChange={(event) =>
                    setNewUserKeyPriceImage2(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-2K 单价
                </label>
                <Input
                  type="number"
                  min="0"
                  value={newUserKeyPriceImage2K}
                  onChange={(event) =>
                    setNewUserKeyPriceImage2K(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  gpt-image-2-4K 单价
                </label>
                <Input
                  type="number"
                  min="0"
                  value={newUserKeyPriceImage4K}
                  onChange={(event) =>
                    setNewUserKeyPriceImage4K(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  标签前缀
                </label>
                <Input
                  value={newUserKeyLabelPrefix}
                  onChange={(event) =>
                    setNewUserKeyLabelPrefix(event.target.value)
                  }
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
                  {isSubmittingUserKeys ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <Plus className="size-4" />
                  )}
                  批量生成
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="minimal-surface-hover overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-0 p-0">
              <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="mr-1 text-lg font-semibold tracking-tight">
                    Key 列表
                  </h3>
                  <Badge
                    variant="secondary"
                    className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700"
                  >
                    {filteredUserKeys.length}
                  </Badge>
                  {selectedUserKeyIds.length > 0 ? (
                    <>
                      <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                        已选择 {selectedUserKeyIds.length} 项
                      </span>
                      <Button
                        variant="ghost"
                        className="h-8 rounded-lg px-3 text-stone-600 hover:bg-stone-100"
                        onClick={() =>
                          openUserKeyExportDialog(
                            selectedUserKeys,
                            "所选用户 key",
                            "user-keys-selected",
                            true,
                          )
                        }
                      >
                        <Download className="size-4" />
                        下载所选
                      </Button>
                      <Button
                        variant="ghost"
                        className="h-8 rounded-lg px-3 text-stone-600 hover:bg-stone-100"
                        onClick={() => setBulkEditUserKeysOpen(true)}
                        disabled={isUpdatingUserKey}
                      >
                        <Pencil className="size-4" />
                        批量编辑
                      </Button>
                      <Button
                        variant="ghost"
                        className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                        onClick={() =>
                          void handleDeleteUserKeys(
                            selectedUserKeys.map((item) => item.key),
                          )
                        }
                        disabled={isDeletingUserKeys}
                      >
                        {isDeletingUserKeys ? (
                          <LoaderCircle className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                        批量删除
                      </Button>
                    </>
                  ) : null}
                </div>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <Button
                    variant="outline"
                    className="h-10 rounded-xl border-stone-200 bg-white/85 px-4 text-stone-700 hover:bg-white"
                    onClick={() =>
                      openUserKeyExportDialog(
                        selectedUserKeys,
                        "所选用户 key",
                        "user-keys-selected",
                        true,
                      )
                    }
                    disabled={selectedUserKeys.length === 0}
                  >
                    <Download className="size-4" />
                    下载所选
                  </Button>
                  <div className="relative min-w-[260px]">
                    <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
                    <Input
                      value={userKeyQuery}
                      onChange={(event) => {
                        setUserKeyQuery(event.target.value);
                        setUserKeyPage(1);
                      }}
                      placeholder="搜索 key 或标签"
                      className="h-10 rounded-xl border-stone-200 bg-white/85 pl-10"
                    />
                  </div>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px] text-left">
                  <thead className="border-b border-stone-100 text-[11px] text-stone-400 uppercase tracking-[0.18em]">
                    <tr>
                      <th className="w-12 px-4 py-3">
                        <Checkbox
                          checked={allCurrentUserKeysSelected}
                          onCheckedChange={(checked) =>
                            toggleSelectAllUserKeys(Boolean(checked))
                          }
                        />
                      </th>
                      <th className="w-56 px-4 py-3">key</th>
                      <th className="w-36 px-4 py-3">标签</th>
                      <th className="w-24 px-4 py-3">状态</th>
                      <th className="w-24 px-4 py-3">次数</th>
                      <th className="w-52 px-4 py-3">单价</th>
                      <th className="w-40 px-4 py-3">创建时间</th>
                      <th className="w-40 px-4 py-3">最近使用</th>
                      <th className="w-28 px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentUserKeys.map((item) => (
                      <tr
                        key={item.id}
                        className="minimal-row-shift border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70"
                      >
                        <td className="px-4 py-3">
                          <Checkbox
                            checked={selectedUserKeyIds.includes(item.id)}
                            onCheckedChange={(checked) => {
                              setSelectedUserKeyIds((prev) =>
                                checked
                                  ? Array.from(new Set([...prev, item.id]))
                                  : prev.filter((id) => id !== item.id),
                              );
                            }}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-medium tracking-tight text-stone-700">
                              {maskToken(item.key, 3, 3)}
                            </span>
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
                        <td className="px-4 py-3 text-stone-500">
                          {item.label || "—"}
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={
                              item.status === "启用" ? "success" : "secondary"
                            }
                            className="rounded-md"
                          >
                            {item.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="info" className="rounded-md">
                            {formatQuota(item.quota)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs leading-5 text-stone-500">
                          {formatUserKeyPricing(item.pricing)}
                        </td>
                        <td className="px-4 py-3 text-xs text-stone-500">
                          {formatDateTime(item.createdAt)}
                        </td>
                        <td className="px-4 py-3 text-xs text-stone-500">
                          {formatDateTime(item.lastUsedAt)}
                        </td>
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
                      <p className="text-sm font-medium text-stone-700">
                        还没有用户 key
                      </p>
                      <p className="text-sm text-stone-500">
                        先设好前缀、数量和初始次数，再批量生成。
                      </p>
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="border-t border-stone-100 px-4 py-4">
                <div className="flex items-center justify-between gap-3 text-sm text-stone-500">
                  <div>
                    显示第{" "}
                    {filteredUserKeys.length === 0 ? 0 : userKeyStartIndex + 1}{" "}
                    -{" "}
                    {Math.min(
                      userKeyStartIndex + ADMIN_SECONDARY_PAGE_SIZE,
                      filteredUserKeys.length,
                    )}{" "}
                    条，共 {filteredUserKeys.length} 条，每页{" "}
                    {ADMIN_SECONDARY_PAGE_SIZE} 条
                  </div>
                  <div className="flex items-center gap-2">
                    <span>
                      {safeUserKeyPage} / {userKeyPageCount} 页
                    </span>
                    <Button
                      variant="outline"
                      className="h-9 rounded-lg border-stone-200 bg-white px-3 text-stone-700"
                      disabled={safeUserKeyPage <= 1}
                      onClick={() =>
                        setUserKeyPage((prev) => Math.max(1, prev - 1))
                      }
                    >
                      <ChevronLeft className="size-4" />
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      className="h-9 rounded-lg border-stone-200 bg-white px-3 text-stone-700"
                      disabled={safeUserKeyPage >= userKeyPageCount}
                      onClick={() =>
                        setUserKeyPage((prev) =>
                          Math.min(userKeyPageCount, prev + 1),
                        )
                      }
                    >
                      下一页
                      <ChevronRight className="size-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
      ) : null}

      {activeTab === "redeemCodes" ? (
        <section className="minimal-fade-soft space-y-4 [animation-delay:180ms]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3">
              <div className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white">
                <Ticket className="size-4" />
              </div>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">兑换码</h2>
                <p className="text-sm text-stone-500">
                  兑换后会给当前用户 key 增加指定额度。
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() => void loadRedeemCodes()}
              disabled={
                isLoadingRedeemCodes ||
                isSubmittingRedeemCodes ||
                isDeletingRedeemCodes
              }
            >
              <RefreshCw
                className={cn(
                  "size-4",
                  isLoadingRedeemCodes ? "animate-spin" : "",
                )}
              />
              刷新兑换码
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() =>
                downloadRedeemCodes(
                  lastCreatedRedeemCodes,
                  "redeem-codes-latest",
                )
              }
              disabled={lastCreatedRedeemCodes.length === 0}
            >
              <Download className="size-4" />
              下载本次 txt
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
              onClick={() =>
                downloadRedeemCodes(
                  selectedRedeemCodes,
                  "redeem-codes-selected",
                )
              }
              disabled={selectedRedeemCodes.length === 0}
            >
              <Download className="size-4" />
              下载所选
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
              onClick={() =>
                void handleDeleteRedeemCodes(
                  usedRedeemCodes.map((item) => item.code),
                )
              }
              disabled={usedRedeemCodes.length === 0 || isDeletingRedeemCodes}
            >
              {isDeletingRedeemCodes ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
              删除已使用
            </Button>
          </div>

          <Card className="minimal-surface-hover rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="grid gap-4 p-4 lg:grid-cols-[140px_140px_180px_minmax(0,1fr)_auto]">
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  前缀
                </label>
                <Input
                  value={newRedeemCodePrefix}
                  onChange={(event) =>
                    setNewRedeemCodePrefix(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  placeholder="RDM"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  数量
                </label>
                <Input
                  type="number"
                  min="1"
                  max="500"
                  value={newRedeemCodeCount}
                  onChange={(event) =>
                    setNewRedeemCodeCount(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  兑换额度
                </label>
                <Select
                  value={newRedeemCodeTargetQuota}
                  onValueChange={(value) =>
                    setNewRedeemCodeTargetQuota(value as "20" | "100")
                  }
                >
                  <SelectTrigger className="h-11 rounded-xl border-stone-200 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="20">20 额度</SelectItem>
                    <SelectItem value="100">100 额度</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-700">
                  备注
                </label>
                <Input
                  value={newRedeemCodeLabel}
                  onChange={(event) =>
                    setNewRedeemCodeLabel(event.target.value)
                  }
                  className="h-11 rounded-xl border-stone-200 bg-white"
                  placeholder="可留空"
                />
              </div>
              <div className="flex items-end">
                <Button
                  className="h-11 w-full rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                  onClick={() => void handleCreateRedeemCodes()}
                  disabled={isSubmittingRedeemCodes}
                >
                  {isSubmittingRedeemCodes ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <Plus className="size-4" />
                  )}
                  生成兑换码
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="minimal-surface-hover overflow-hidden rounded-2xl border-white/80 bg-white/90 shadow-sm">
            <CardContent className="space-y-0 p-0">
              <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-semibold tracking-tight">
                    兑换码列表
                  </h3>
                  <Badge
                    variant="secondary"
                    className="rounded-lg bg-stone-200 px-2 py-0.5 text-stone-700"
                  >
                    {filteredRedeemCodes.length}
                  </Badge>
                  {selectedRedeemCodeIds.length > 0 ? (
                    <>
                      <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                        已选择 {selectedRedeemCodeIds.length} 项
                      </span>
                      <Button
                        variant="ghost"
                        className="h-8 rounded-lg px-3 text-stone-600 hover:bg-stone-100"
                        onClick={() =>
                          downloadRedeemCodes(
                            selectedRedeemCodes,
                            "redeem-codes-selected",
                          )
                        }
                      >
                        <Download className="size-4" />
                        下载所选
                      </Button>
                      <Button
                        variant="ghost"
                        className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
                        onClick={() =>
                          void handleDeleteRedeemCodes(
                            selectedRedeemCodes.map((item) => item.code),
                          )
                        }
                        disabled={isDeletingRedeemCodes}
                      >
                        {isDeletingRedeemCodes ? (
                          <LoaderCircle className="size-4 animate-spin" />
                        ) : (
                          <Trash2 className="size-4" />
                        )}
                        批量删除
                      </Button>
                    </>
                  ) : null}
                </div>
                <div className="relative min-w-[260px]">
                  <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
                  <Input
                    value={redeemCodeQuery}
                    onChange={(event) => {
                      setRedeemCodeQuery(event.target.value);
                      setRedeemCodePage(1);
                    }}
                    placeholder="搜索兑换码或备注"
                    className="h-10 rounded-xl border-stone-200 bg-white/85 pl-10"
                  />
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px] text-left">
                  <thead className="border-b border-stone-100 text-[11px] text-stone-400 uppercase tracking-[0.18em]">
                    <tr>
                      <th className="w-12 px-4 py-3">
                        <Checkbox
                          checked={allCurrentRedeemCodesSelected}
                          onCheckedChange={(checked) =>
                            toggleSelectAllRedeemCodes(Boolean(checked))
                          }
                        />
                      </th>
                      <th className="w-56 px-4 py-3">兑换码</th>
                      <th className="w-24 px-4 py-3">状态</th>
                      <th className="w-24 px-4 py-3">增加额度</th>
                      <th className="w-40 px-4 py-3">备注</th>
                      <th className="w-40 px-4 py-3">创建时间</th>
                      <th className="w-40 px-4 py-3">使用时间</th>
                      <th className="w-40 px-4 py-3">使用 key</th>
                      <th className="w-20 px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentRedeemCodes.map((item) => (
                      <tr
                        key={item.id}
                        className="minimal-row-shift border-b border-stone-100/80 text-sm text-stone-600 transition-colors hover:bg-stone-50/70"
                      >
                        <td className="px-4 py-3">
                          <Checkbox
                            checked={selectedRedeemCodeIds.includes(item.id)}
                            onCheckedChange={(checked) => {
                              setSelectedRedeemCodeIds((prev) =>
                                checked
                                  ? Array.from(new Set([...prev, item.id]))
                                  : prev.filter((id) => id !== item.id),
                              );
                            }}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="font-medium tracking-tight text-stone-700">
                              {item.code}
                            </span>
                            <button
                              type="button"
                              className="rounded-lg p-1 text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                              onClick={() => {
                                void navigator.clipboard.writeText(item.code);
                                toast.success("兑换码已复制");
                              }}
                            >
                              <Copy className="size-4" />
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={
                              item.status === "未使用" ? "success" : "secondary"
                            }
                            className="rounded-md"
                          >
                            {item.status}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="info" className="rounded-md">
                            {formatQuota(item.targetQuota)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-stone-500">
                          {item.label || "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-stone-500">
                          {formatDateTime(item.createdAt)}
                        </td>
                        <td className="px-4 py-3 text-xs text-stone-500">
                          {formatDateTime(item.usedAt)}
                        </td>
                        <td className="px-4 py-3 text-xs text-stone-500">
                          {item.usedByKey
                            ? maskToken(item.usedByKey, 3, 3)
                            : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            className="rounded-lg p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500"
                            onClick={() =>
                              void handleDeleteRedeemCode(item.code)
                            }
                            disabled={isDeletingRedeemCodes}
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {!isLoadingRedeemCodes && filteredRedeemCodes.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
                    <div className="rounded-xl bg-stone-100 p-3 text-stone-500">
                      <Ticket className="size-5" />
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-stone-700">
                        还没有兑换码
                      </p>
                      <p className="text-sm text-stone-500">
                        先选额度和数量，再生成一批。
                      </p>
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="border-t border-stone-100 px-4 py-4">
                <div className="flex items-center justify-between gap-3 text-sm text-stone-500">
                  <div>
                    显示第{" "}
                    {filteredRedeemCodes.length === 0
                      ? 0
                      : redeemCodeStartIndex + 1}{" "}
                    -{" "}
                    {Math.min(
                      redeemCodeStartIndex + ADMIN_SECONDARY_PAGE_SIZE,
                      filteredRedeemCodes.length,
                    )}{" "}
                    条，共 {filteredRedeemCodes.length} 条，每页{" "}
                    {ADMIN_SECONDARY_PAGE_SIZE} 条
                  </div>
                  <div className="flex items-center gap-2">
                    <span>
                      {safeRedeemCodePage} / {redeemCodePageCount} 页
                    </span>
                    <Button
                      variant="outline"
                      className="h-9 rounded-lg border-stone-200 bg-white px-3 text-stone-700"
                      disabled={safeRedeemCodePage <= 1}
                      onClick={() =>
                        setRedeemCodePage((prev) => Math.max(1, prev - 1))
                      }
                    >
                      <ChevronLeft className="size-4" />
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      className="h-9 rounded-lg border-stone-200 bg-white px-3 text-stone-700"
                      disabled={safeRedeemCodePage >= redeemCodePageCount}
                      onClick={() =>
                        setRedeemCodePage((prev) =>
                          Math.min(redeemCodePageCount, prev + 1),
                        )
                      }
                    >
                      下一页
                      <ChevronRight className="size-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
      ) : null}

      {activeTab === "data" ? (
        <section className="minimal-fade-soft space-y-4 [animation-delay:180ms]">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3">
              <div className="inline-flex size-10 items-center justify-center rounded-xl bg-stone-950 text-white">
                <Database className="size-4" />
              </div>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">
                  数据管理
                </h2>
                <p className="text-sm text-stone-500">
                  查看 SQLite、备份、本地保存和 S3 设置。
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
                onClick={() => {
                  void loadDataManagement();
                  void loadImageRequests();
                }}
                disabled={isLoadingDataManagement || isLoadingImageRequests}
              >
                <RefreshCw className={cn("size-4", isLoadingDataManagement || isLoadingImageRequests ? "animate-spin" : "")} />
                刷新
              </Button>
              <Button
                className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                onClick={() => void handleCreateDataBackup()}
                disabled={isCreatingBackup}
              >
                {isCreatingBackup ? <LoaderCircle className="size-4 animate-spin" /> : <HardDrive className="size-4" />}
                手动备份
              </Button>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="minimal-card lg:col-span-2">
              <CardContent className="space-y-4 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-base font-semibold text-stone-900">
                      SQLite 状态
                    </h3>
                    <p className="mt-1 text-sm text-stone-500">
                      {dataStatus?.sqlite_path || "—"}
                    </p>
                  </div>
                  <Badge variant={dataStatus?.exists ? "success" : "danger"}>
                    {dataStatus?.exists ? "可用" : "未创建"}
                  </Badge>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
                    <div className="text-xs text-stone-500">数据库大小</div>
                    <div className="mt-1 text-lg font-semibold text-stone-900">
                      {formatBytes(dataStatus?.size_bytes || 0)}
                    </div>
                  </div>
                  <div className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
                    <div className="text-xs text-stone-500">备份目录</div>
                    <div className="mt-1 truncate text-sm font-medium text-stone-900">
                      {dataStatus?.backup_dir || "—"}
                    </div>
                  </div>
                  <div className="rounded-xl border border-stone-100 bg-stone-50/70 p-3">
                    <div className="text-xs text-stone-500">备份占用</div>
                    <div className="mt-1 text-lg font-semibold text-stone-900">
                      {formatBytes(dataStatus?.backup_size_bytes || 0)}
                    </div>
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(dataStatus?.tables || {}).map(([name, count]) => (
                    <div key={name} className="flex items-center justify-between rounded-lg border border-stone-100 px-3 py-2 text-sm">
                      <span className="text-stone-500">{name}</span>
                      <span className="font-medium text-stone-900">{count}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card className="minimal-card">
              <CardContent className="space-y-3 p-5">
                <h3 className="text-base font-semibold text-stone-900">
                  保存设置
                </h3>
                <label className="flex items-center gap-2 text-sm text-stone-700">
                  <Checkbox
                    checked={Boolean(dataSettings?.backup_enabled)}
                    onCheckedChange={(checked) =>
                      setDataSettings((prev) => (prev ? { ...prev, backup_enabled: Boolean(checked) } : prev))
                    }
                  />
                  开启定时备份
                </label>
                <label className="flex items-center gap-2 text-sm text-stone-700">
                  <Checkbox
                    checked={Boolean(dataSettings?.save_image_conversations)}
                    onCheckedChange={(checked) =>
                      setDataSettings((prev) => (prev ? { ...prev, save_image_conversations: Boolean(checked) } : prev))
                    }
                  />
                  保存图片会话
                </label>
                <label className="flex items-center gap-2 text-sm text-stone-700">
                  <Checkbox
                    checked={Boolean(dataSettings?.save_logs)}
                    onCheckedChange={(checked) =>
                      setDataSettings((prev) => (prev ? { ...prev, save_logs: Boolean(checked) } : prev))
                    }
                  />
                  保存运行日志
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    type="number"
                    min={0}
                    value={dataSettings?.backup_interval_minutes ?? 0}
                    onChange={(event) =>
                      setDataSettings((prev) =>
                        prev ? { ...prev, backup_interval_minutes: Math.max(0, Number(event.target.value || 0)) } : prev,
                      )
                    }
                    className="h-10 rounded-xl border-stone-200"
                    placeholder="间隔分钟"
                  />
                  <Input
                    type="number"
                    min={1}
                    value={dataSettings?.backup_max_bytes ?? 1}
                    onChange={(event) =>
                      setDataSettings((prev) =>
                        prev ? { ...prev, backup_max_bytes: Math.max(1, Number(event.target.value || 1)) } : prev,
                      )
                    }
                    className="h-10 rounded-xl border-stone-200"
                    placeholder="最大字节"
                  />
                </div>
                <Button
                  className="h-10 w-full rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800"
                  onClick={() => void handleSaveDataSettings()}
                  disabled={isSavingDataSettings || !dataSettings}
                >
                  {isSavingDataSettings ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                  保存设置
                </Button>
              </CardContent>
            </Card>
          </div>

          <Card className="minimal-card">
            <CardContent className="space-y-4 p-5">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="text-base font-semibold text-stone-900">
                    S3 备份上传
                  </h3>
                  <p className="mt-1 text-sm text-stone-500">
                    只上传备份包，不改变图片读取方式。
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                    onClick={() => void handleTestDataS3()}
                    disabled={isTestingS3 || !dataSettings}
                  >
                    {isTestingS3 ? <LoaderCircle className="size-4 animate-spin" /> : null}
                    测试 S3
                  </Button>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                <Input value={dataSettings?.s3.endpoint || ""} onChange={(event) => updateDataS3Field("endpoint", event.target.value)} placeholder="endpoint" className="h-10 rounded-xl border-stone-200" />
                <Input value={dataSettings?.s3.region || ""} onChange={(event) => updateDataS3Field("region", event.target.value)} placeholder="region" className="h-10 rounded-xl border-stone-200" />
                <Input value={dataSettings?.s3.bucket || ""} onChange={(event) => updateDataS3Field("bucket", event.target.value)} placeholder="bucket" className="h-10 rounded-xl border-stone-200" />
                <Input value={dataSettings?.s3.prefix || ""} onChange={(event) => updateDataS3Field("prefix", event.target.value)} placeholder="prefix" className="h-10 rounded-xl border-stone-200" />
                <Input value={dataSettings?.s3.access_key_id || ""} onChange={(event) => updateDataS3Field("access_key_id", event.target.value)} placeholder="access key id" className="h-10 rounded-xl border-stone-200" />
                <Input value={dataSettings?.s3.secret_access_key || ""} onChange={(event) => updateDataS3Field("secret_access_key", event.target.value)} placeholder="secret access key" type="password" className="h-10 rounded-xl border-stone-200" />
                <label className="flex items-center gap-2 rounded-xl border border-stone-100 px-3 text-sm text-stone-700">
                  <Checkbox checked={Boolean(dataSettings?.s3.enabled)} onCheckedChange={(checked) => updateDataS3Field("enabled", Boolean(checked))} />
                  启用上传
                </label>
                <label className="flex items-center gap-2 rounded-xl border border-stone-100 px-3 text-sm text-stone-700">
                  <Checkbox checked={Boolean(dataSettings?.s3.force_path_style)} onCheckedChange={(checked) => updateDataS3Field("force_path_style", Boolean(checked))} />
                  path style
                </label>
              </div>
            </CardContent>
          </Card>

          <Card className="minimal-card">
            <CardContent className="space-y-4 p-5">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="flex items-center gap-2 text-base font-semibold text-stone-900">
                    <FileSearch className="size-4" />
                    请求记录
                  </h3>
                  <p className="mt-1 text-sm text-stone-500">
                    只保存摘要、耗时、扣费和路线，不保存完整 prompt 或图片内容。
                  </p>
                </div>
                <Button
                  variant="outline"
                  className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={() => void loadImageRequests()}
                  disabled={isLoadingImageRequests}
                >
                  <RefreshCw className={cn("size-4", isLoadingImageRequests ? "animate-spin" : "")} />
                  刷新记录
                </Button>
              </div>

              <div className="grid gap-3 md:grid-cols-4">
                <Input
                  value={imageRequestQuery}
                  onChange={(event) => setImageRequestQuery(event.target.value)}
                  placeholder="请求 id"
                  className="h-10 rounded-xl border-stone-200"
                />
                <Select value={imageRequestStatusFilter} onValueChange={(value) => setImageRequestStatusFilter(value as ImageRequestStatus | "all")}>
                  <SelectTrigger className="h-10 rounded-xl border-stone-200">
                    <SelectValue placeholder="状态" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部状态</SelectItem>
                    {["accepted", "waiting", "assigning_account", "running", "finished", "failed", "rejected"].map((status) => (
                      <SelectItem key={status} value={status}>
                        {status}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={imageRequestModelFilter} onValueChange={(value) => setImageRequestModelFilter(value as ImageModel | "all")}>
                  <SelectTrigger className="h-10 rounded-xl border-stone-200">
                    <SelectValue placeholder="模型" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部模型</SelectItem>
                    {imageModels.map((model) => (
                      <SelectItem key={model} value={model}>
                        {model}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={imageRequestEndpointFilter} onValueChange={setImageRequestEndpointFilter}>
                  <SelectTrigger className="h-10 rounded-xl border-stone-200">
                    <SelectValue placeholder="入口" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部入口</SelectItem>
                    <SelectItem value="/v1/responses">/v1/responses</SelectItem>
                    <SelectItem value="/v1/images/generations">/v1/images/generations</SelectItem>
                    <SelectItem value="/v1/images/edits">/v1/images/edits</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end">
                <Button
                  variant="outline"
                  className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={() => void loadImageRequests()}
                  disabled={isLoadingImageRequests}
                >
                  <Search className="size-4" />
                  查询
                </Button>
              </div>

              <div className="overflow-x-auto rounded-xl border border-stone-100">
                <table className="w-full min-w-[1120px] text-left text-sm">
                  <thead className="bg-stone-50 text-xs text-stone-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">时间</th>
                      <th className="px-3 py-2 font-medium">状态</th>
                      <th className="px-3 py-2 font-medium">入口</th>
                      <th className="px-3 py-2 font-medium">模型</th>
                      <th className="px-3 py-2 font-medium">尺寸</th>
                      <th className="px-3 py-2 font-medium">张数</th>
                      <th className="px-3 py-2 font-medium">总耗时</th>
                      <th className="px-3 py-2 font-medium">等待</th>
                      <th className="px-3 py-2 font-medium">运行</th>
                      <th className="px-3 py-2 font-medium">扣费</th>
                      <th className="px-3 py-2 font-medium">key 标签</th>
                      <th className="px-3 py-2 font-medium">请求 id</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-100">
                    {imageRequests.length === 0 ? (
                      <tr>
                        <td className="px-3 py-4 text-stone-500" colSpan={12}>
                          暂无请求记录
                        </td>
                      </tr>
                    ) : (
                      imageRequests.map((item) => (
                        <tr
                          key={item.request_id}
                          className="cursor-pointer hover:bg-stone-50"
                          onClick={() => setSelectedImageRequest(item)}
                        >
                          <td className="px-3 py-2 text-stone-600">{formatDateTime(item.created_at)}</td>
                          <td className="px-3 py-2">
                            <Badge variant={item.status === "finished" ? "success" : item.status === "failed" || item.status === "rejected" ? "danger" : "secondary"}>
                              {item.status}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-stone-600">{item.endpoint}</td>
                          <td className="px-3 py-2 text-stone-900">{item.model || "—"}</td>
                          <td className="px-3 py-2 text-stone-600">{item.size || "auto"}</td>
                          <td className="px-3 py-2 text-stone-600">{item.n}</td>
                          <td className="px-3 py-2 text-stone-600">{formatDurationMs(item.total_ms)}</td>
                          <td className="px-3 py-2 text-stone-600">{formatDurationMs(item.queue_wait_ms)}</td>
                          <td className="px-3 py-2 text-stone-600">{formatDurationMs(item.running_ms)}</td>
                          <td className="px-3 py-2 text-stone-600">{item.charged_quota ?? "—"}</td>
                          <td className="px-3 py-2 text-stone-600">{item.user_key_label || item.auth_type}</td>
                          <td className="max-w-[180px] truncate px-3 py-2 font-mono text-xs text-stone-500">{item.request_id}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="minimal-card">
              <CardContent className="p-0">
                <div className="border-b border-stone-100 px-5 py-4">
                  <h3 className="text-base font-semibold text-stone-900">
                    备份记录
                  </h3>
                </div>
                <div className="divide-y divide-stone-100">
                  {dataBackups.length === 0 ? (
                    <div className="p-5 text-sm text-stone-500">暂无备份</div>
                  ) : (
                    dataBackups.slice(0, 8).map((item) => (
                      <div key={item.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                        <div className="min-w-0">
                          <div className="truncate font-medium text-stone-900">{item.id}</div>
                          <div className="truncate text-xs text-stone-500">{item.path}</div>
                        </div>
                        <div className="shrink-0 text-right">
                          <Badge variant={item.status === "success" ? "success" : "danger"}>{item.status}</Badge>
                          <div className="mt-1 text-xs text-stone-500">{formatBytes(item.size_bytes)}</div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="minimal-card">
              <CardContent className="p-0">
                <div className="border-b border-stone-100 px-5 py-4">
                  <h3 className="text-base font-semibold text-stone-900">
                    最近日志
                  </h3>
                </div>
                <div className="divide-y divide-stone-100">
                  {dataLogs.length === 0 ? (
                    <div className="p-5 text-sm text-stone-500">暂无日志</div>
                  ) : (
                    dataLogs.slice(0, 10).map((item) => (
                      <div key={item.id} className="px-5 py-3 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium text-stone-900">{item.component}</div>
                          <span className="text-xs text-stone-500">{formatDateTime(item.created_at)}</span>
                        </div>
                        <div className="mt-1 text-stone-600">{item.message}</div>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      ) : null}

      <Dialog open={Boolean(selectedImageRequest)} onOpenChange={(open) => !open && setSelectedImageRequest(null)}>
        <DialogContent className="max-w-3xl rounded-2xl border-stone-200 bg-white">
          <DialogHeader>
            <DialogTitle>请求详情</DialogTitle>
            <DialogDescription>
              {selectedImageRequest?.request_id || "—"}
            </DialogDescription>
          </DialogHeader>
          {selectedImageRequest ? (
            <div className="grid gap-4 text-sm md:grid-cols-2">
              <div className="space-y-2 rounded-xl border border-stone-100 p-3">
                <div className="font-medium text-stone-900">阶段时间</div>
                <div className="text-stone-600">接收：{formatDateTime(selectedImageRequest.accepted_at)}</div>
                <div className="text-stone-600">排队：{formatDateTime(selectedImageRequest.queued_at)}</div>
                <div className="text-stone-600">分配账号：{formatDateTime(selectedImageRequest.started_at)}</div>
                <div className="text-stone-600">运行：{formatDateTime(selectedImageRequest.running_at)}</div>
                <div className="text-stone-600">结束：{formatDateTime(selectedImageRequest.finished_at)}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-stone-100 p-3">
                <div className="font-medium text-stone-900">耗时</div>
                <div className="text-stone-600">等待：{formatDurationMs(selectedImageRequest.queue_wait_ms)}</div>
                <div className="text-stone-600">分配：{formatDurationMs(selectedImageRequest.assigning_ms)}</div>
                <div className="text-stone-600">运行：{formatDurationMs(selectedImageRequest.running_ms)}</div>
                <div className="text-stone-600">总计：{formatDurationMs(selectedImageRequest.total_ms)}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-stone-100 p-3">
                <div className="font-medium text-stone-900">计费</div>
                <div className="text-stone-600">请求张数：{selectedImageRequest.requested_count ?? selectedImageRequest.n}</div>
                <div className="text-stone-600">成功：{selectedImageRequest.succeeded_count ?? "—"}</div>
                <div className="text-stone-600">失败：{selectedImageRequest.failed_count ?? "—"}</div>
                <div className="text-stone-600">单价：{selectedImageRequest.unit_cost ?? "—"}</div>
                <div className="text-stone-600">扣费：{selectedImageRequest.charged_quota ?? "—"}</div>
                <div className="text-stone-600">剩余：{selectedImageRequest.remaining_quota ?? "—"}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-stone-100 p-3">
                <div className="font-medium text-stone-900">路线</div>
                <div className="text-stone-600">账号类型：{selectedImageRequest.account_type || "—"}</div>
                <div className="text-stone-600">路线：{selectedImageRequest.route || "—"}</div>
                <div className="text-stone-600">尝试次数：{selectedImageRequest.attempt_count ?? "—"}</div>
                <div className="text-stone-600">使用回退：{selectedImageRequest.fallback_used ? "是" : "否"}</div>
                <div className="truncate text-stone-600">账号哈希：{selectedImageRequest.account_token_hash || "—"}</div>
              </div>
              <div className="space-y-2 rounded-xl border border-stone-100 p-3 md:col-span-2">
                <div className="font-medium text-stone-900">内容摘要</div>
                <div className="text-stone-600">prompt 摘要：{selectedImageRequest.prompt_preview || "—"}</div>
                <div className="break-all font-mono text-xs text-stone-500">prompt_hash：{selectedImageRequest.prompt_hash || "—"}</div>
              </div>
              {(selectedImageRequest.error_message || selectedImageRequest.upstream_error) ? (
                <div className="space-y-2 rounded-xl border border-red-100 bg-red-50 p-3 md:col-span-2">
                  <div className="font-medium text-red-900">错误</div>
                  <div className="text-red-700">{selectedImageRequest.error_message || "—"}</div>
                  <div className="text-red-700">{selectedImageRequest.upstream_error || ""}</div>
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
