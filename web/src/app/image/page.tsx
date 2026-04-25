"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Copy,
  Download,
  Images,
  ImagePlus,
  LoaderCircle,
  MessageSquarePlus,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  buildImageDataUrl,
  detectImageFileExtension,
  detectImageMimeType,
} from "@/lib/image-data";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchImageQueueStatus,
  fetchQuotaSummary,
  generateImage,
  uploadInputImage,
  type ImageModel,
  type ImageQueueItem,
} from "@/lib/api";
import {
  clearImageConversations,
  deleteImageConversation,
  listImageConversations,
  replaceImageConversations,
  saveImageConversation,
  type ImageConversation,
  type StoredInputImage,
  type StoredImage,
} from "@/store/image-conversations";
import { getStoredAuthKey } from "@/store/auth";
import { cn } from "@/lib/utils";

const imageModelMeta: Record<ImageModel, { helperText: string }> = {
  "gpt-image-1": {
    helperText: "gpt-image-1 已下架。",
  },
  "gpt-image-2": {
    helperText: "当前直接走真实 gpt-image-2 生图链路。",
  },
};

const DEFAULT_IMAGE_PRICING: Record<ImageModel, number> = {
  "gpt-image-1": 0,
  "gpt-image-2": 2,
};
const MAX_IMAGES_PER_REQUEST = 2;
const IMAGE_COUNT_OPTIONS = Array.from(
  { length: MAX_IMAGES_PER_REQUEST },
  (_, index) => String(index + 1),
);
const MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024;
const activeGenerationKeys = new Set<string>();

function buildConversationTitle(prompt: string) {
  const trimmed = prompt.trim();
  if (trimmed.length <= 5) {
    return trimmed;
  }
  return `${trimmed.slice(0, 5)}...`;
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function downloadBase64Image(
  base64: string,
  fileName: string,
  mimeType?: string,
) {
  const binary = window.atob(base64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const resolvedMimeType =
    String(mimeType || "").trim() || detectImageMimeType(base64);
  const blob = new Blob([bytes], { type: resolvedMimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

type PreviewableImage = {
  id: string;
  originalIndex: number;
  src: string;
  alt: string;
  b64Json: string;
  mimeType: string;
};

type PendingInputImage = {
  id: string;
  fileId: string;
  fileName: string;
  dataUrl: string;
  sizeBytes: number;
  clientConversationId: string;
};

type ImageQueueStatusSnapshot = Awaited<
  ReturnType<typeof fetchImageQueueStatus>
>;

function formatInputImageSize(sizeBytes: number) {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`;
}

function formatQueueItemLabel(
  item: ImageQueueItem,
  localTitles: Record<string, string>,
) {
  const localTitle = String(localTitles[item.request_id] || "").trim();
  if (localTitle) {
    return localTitle;
  }
  return `请求 ${item.request_id.slice(-8)}`;
}

function formatQueueProgressText(item: ImageQueueItem | null | undefined) {
  if (!item) {
    return "正在同步排队状态";
  }
  if (item.status === "waiting") {
    if (item.position) {
      return `排队中，第 ${item.position} 位，前面还有 ${Math.max(0, Number(item.ahead || 0))} 个`;
    }
    return "排队中";
  }
  if (item.status === "assigning_account") {
    return "已轮到当前请求，正在等待可用账号";
  }
  if (item.status === "running") {
    return "已开始生成，正在等待图片返回";
  }
  if (item.status === "failed") {
    return item.error || "生成失败";
  }
  if (item.status === "finished") {
    return "已完成";
  }
  return "正在同步排队状态";
}

function formatQueueStatusBadge(item: ImageQueueItem) {
  if (item.status === "waiting") {
    return "排队中";
  }
  if (item.status === "assigning_account") {
    return "等账号";
  }
  if (item.status === "running") {
    return "生成中";
  }
  if (item.status === "finished") {
    return "已完成";
  }
  if (item.status === "failed") {
    return "失败";
  }
  return item.status;
}

function createClientRequestId(prefix = "") {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    const value = crypto.randomUUID();
    return prefix ? `${prefix}${value}` : value;
  }
  return prefix ? `${prefix}fallback-request-id` : "fallback-request-id";
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      if (!result) {
        reject(new Error("读取图片失败"));
        return;
      }
      resolve(result);
    };
    reader.onerror = () => {
      reject(new Error("读取图片失败"));
    };
    reader.readAsDataURL(file);
  });
}

async function normalizeConversationHistory(
  items: ImageConversation[],
  scope: string,
) {
  const normalized = items.map((item) =>
    (item.status === "queued" ||
      item.status === "assigning_account" ||
      item.status === "running") &&
    !activeGenerationKeys.has(`${scope}:${item.id}`)
      ? {
          ...item,
          status: "error" as const,
          error: item.images.some((image) => image.status === "success")
            ? item.error || item.lastError || "页面刷新后未找回运行态"
            : "页面刷新后未找回运行态",
          lastError: item.lastError || "页面刷新后未找回运行态",
          requestFinishedAt: item.requestFinishedAt || new Date().toISOString(),
          images: item.images.map((image) =>
            image.status === "loading"
              ? {
                  ...image,
                  status: "error" as const,
                  error: "页面刷新后未找回运行态",
                }
              : image,
          ),
        }
      : item,
  );

  if (normalized.some((item, index) => item !== items[index])) {
    await replaceImageConversations(scope, normalized);
  }

  return normalized;
}

export default function ImagePage() {
  const didLoadQuotaRef = useRef(false);
  const conversationsRef = useRef<ImageConversation[]>([]);
  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageModel, setImageModel] = useState<ImageModel>("gpt-image-2");
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [conversationScope, setConversationScope] = useState<string | null>(
    null,
  );
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isUploadingInputImage, setIsUploadingInputImage] = useState(false);
  const [inputImage, setInputImage] = useState<PendingInputImage | null>(null);
  const [availableQuota, setAvailableQuota] = useState<number | null>(null);
  const [currentPricing, setCurrentPricing] = useState<Record<
    ImageModel,
    number
  > | null>(null);
  const [queueStatus, setQueueStatus] =
    useState<ImageQueueStatusSnapshot | null>(null);
  const [queueTitles, setQueueTitles] = useState<Record<string, string>>({});
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputImageRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const prompt = params.get("prompt");
    if (!prompt) {
      return;
    }
    const timer = window.setTimeout(() => {
      setImagePrompt(prompt);
      textareaRef.current?.focus();
      params.delete("prompt");
      const nextQuery = params.toString();
      const nextUrl = nextQuery ? `/image?${nextQuery}` : "/image";
      window.history.replaceState({}, "", nextUrl);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) {
      return;
    }

    const syncHeight = () => {
      const lineHeight =
        Number.parseFloat(window.getComputedStyle(element).lineHeight) || 24;
      const minHeight = Math.round(lineHeight * 1.5);
      const maxHeight = Math.max(
        Math.round(lineHeight * 3),
        Math.min(
          Math.round(window.innerHeight * 0.22),
          Math.round(lineHeight * 8),
        ),
      );

      element.style.height = "auto";
      const nextHeight = Math.min(
        Math.max(element.scrollHeight, minHeight),
        maxHeight,
      );
      element.style.height = `${nextHeight}px`;
      element.style.overflowY =
        element.scrollHeight > maxHeight ? "auto" : "hidden";
    };

    syncHeight();
    window.addEventListener("resize", syncHeight);
    return () => {
      window.removeEventListener("resize", syncHeight);
    };
  }, [imagePrompt]);

  const parsedCount = useMemo(
    () =>
      Math.max(1, Math.min(MAX_IMAGES_PER_REQUEST, Number(imageCount) || 1)),
    [imageCount],
  );
  const effectivePricing = useMemo(
    () => currentPricing || DEFAULT_IMAGE_PRICING,
    [currentPricing],
  );
  const currentUnitCost = useMemo(
    () => Math.max(0, Number(effectivePricing[imageModel] || 0)),
    [effectivePricing, imageModel],
  );
  const requestCost = useMemo(
    () => parsedCount * currentUnitCost,
    [currentUnitCost, parsedCount],
  );
  const isQuotaInsufficient = useMemo(
    () => availableQuota !== null && requestCost > Math.max(0, availableQuota),
    [availableQuota, requestCost],
  );
  const availableQuotaLabel =
    availableQuota === null ? "加载中" : String(Math.max(0, availableQuota));
  const selectedConversation = useMemo(
    () =>
      conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const activeRequestIds = useMemo(
    () =>
      Array.from(
        new Set(
          conversations
            .filter(
              (item) =>
                Boolean(item.queueRequestId) &&
                (item.status === "queued" ||
                  item.status === "assigning_account" ||
                  item.status === "running"),
            )
            .map((item) => String(item.queueRequestId || "").trim())
            .filter(Boolean),
        ),
      ),
    [conversations],
  );
  const selectedConversationRequestId = selectedConversation?.queueRequestId || null;
  const isComposerGenerating = activeRequestIds.length > 0;
  const previewableImages = useMemo<PreviewableImage[]>(
    () =>
      (selectedConversation?.images || []).flatMap((image, index) =>
        image.status === "success" && image.b64_json
          ? [
              {
                id: image.id,
                originalIndex: index,
                src: buildImageDataUrl(image.b64_json, image.mimeType),
                alt: `Generated result ${index + 1}`,
                b64Json: image.b64_json,
                mimeType:
                  String(image.mimeType || "").trim() ||
                  detectImageMimeType(image.b64_json),
              },
            ]
          : [],
      ),
    [selectedConversation],
  );
  const activePreviewImageId = useMemo(
    () =>
      previewableImages.some((image) => image.id === previewImageId)
        ? previewImageId
        : null,
    [previewImageId, previewableImages],
  );
  const previewImageIndex = useMemo(
    () =>
      previewableImages.findIndex((image) => image.id === activePreviewImageId),
    [activePreviewImageId, previewableImages],
  );
  const previewImage =
    previewImageIndex >= 0 ? previewableImages[previewImageIndex] : null;
  const hasPreviousPreviewImage = previewImageIndex > 0;
  const hasNextPreviewImage =
    previewImageIndex >= 0 && previewImageIndex < previewableImages.length - 1;
  const currentQueueRequest = useMemo(() => {
    if (!selectedConversation?.queueRequestId) {
      return null;
    }
    return (
      (queueStatus?.items || []).find(
        (item) => item.request_id === selectedConversation.queueRequestId,
      ) || null
    );
  }, [queueStatus, selectedConversation]);
  const activeQueueItems = useMemo(
    () =>
      (queueStatus?.items || []).filter(
        (item) =>
          item.status === "waiting" ||
          item.status === "assigning_account" ||
          item.status === "running",
      ),
    [queueStatus],
  );
  const currentQueueProgressText = useMemo(
    () => formatQueueProgressText(currentQueueRequest),
    [currentQueueRequest],
  );

  useEffect(() => {
    let cancelled = false;

    const loadScope = async () => {
      try {
        const authKey = await getStoredAuthKey();
        if (!cancelled) {
          setConversationScope(String(authKey || "").trim() || "__anonymous__");
        }
      } catch (error) {
        if (!cancelled) {
          setConversationScope("__anonymous__");
        }
      }
    };

    void loadScope();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (conversationScope === null) {
      return;
    }

    let cancelled = false;

    const loadHistory = async () => {
      setIsLoadingHistory(true);
      setSelectedConversationId(null);
      setPreviewImageId(null);
      try {
        const items = await listImageConversations(conversationScope);
        const normalizedItems = await normalizeConversationHistory(
          items,
          conversationScope,
        );
        if (cancelled) {
          return;
        }
        conversationsRef.current = normalizedItems;
        setConversations(normalizedItems);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "读取会话记录失败";
        toast.error(message);
      } finally {
        if (!cancelled) {
          setIsLoadingHistory(false);
        }
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [conversationScope]);

  const loadQuota = useCallback(async () => {
    try {
      const data = await fetchQuotaSummary();
      setAvailableQuota(Math.max(0, Number(data.available_quota || 0)));
      if (data.pricing) {
        setCurrentPricing({
          "gpt-image-1": Math.max(0, Number(data.pricing["gpt-image-1"] || 0)),
          "gpt-image-2": Math.max(0, Number(data.pricing["gpt-image-2"] || 0)),
        });
      } else {
        setCurrentPricing(null);
      }
    } catch {
      setAvailableQuota(null);
      setCurrentPricing(null);
    }
  }, []);

  useEffect(() => {
    if (didLoadQuotaRef.current) {
      return;
    }
    didLoadQuotaRef.current = true;

    const syncQuota = async () => {
      await loadQuota();
    };

    const handleFocus = () => {
      void syncQuota();
    };
    const handleQuotaChanged = () => {
      void syncQuota();
    };

    void syncQuota();
    window.addEventListener("focus", handleFocus);
    window.addEventListener("chatgpt2api:quota-changed", handleQuotaChanged);
    return () => {
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener(
        "chatgpt2api:quota-changed",
        handleQuotaChanged,
      );
    };
  }, [loadQuota]);

  useEffect(() => {
    if (conversationScope === null) {
      return;
    }

    let cancelled = false;

    const syncQueueStatus = async () => {
      try {
        const snapshots = await Promise.all(
          activeRequestIds.map((requestId) =>
            fetchImageQueueStatus(requestId).catch(() => null),
          ),
        );
        if (!cancelled) {
          const mergedItems = snapshots.flatMap((snapshot) => snapshot?.items || []);
          const uniqueItems = Array.from(
            new Map(mergedItems.map((item) => [item.request_id, item])).values(),
          );
          const baseSnapshot = snapshots.find((snapshot) => snapshot) || null;
          setQueueStatus(
            baseSnapshot
              ? {
                  ...baseSnapshot,
                  request:
                    uniqueItems.find(
                      (item) => item.request_id === selectedConversationRequestId,
                    ) || null,
                  items: uniqueItems,
                }
              : null,
          );
        }
      } catch {
        if (!cancelled) {
          setQueueStatus(null);
        }
      }
    };

    void syncQueueStatus();
    const intervalId = window.setInterval(() => {
      void syncQueueStatus();
    }, 1500);
    const handleFocus = () => {
      void syncQueueStatus();
    };
    window.addEventListener("focus", handleFocus);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleFocus);
    };
  }, [activeRequestIds, conversationScope, selectedConversationRequestId]);

  useEffect(() => {
    if (!selectedConversation && !isComposerGenerating) {
      return;
    }

    resultsViewportRef.current?.scrollTo({
      top: resultsViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation, isComposerGenerating]);

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const persistConversation = async (conversation: ImageConversation) => {
    if (!conversationScope) {
      return;
    }
    conversationsRef.current = [
      conversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    setConversations((prev) => {
      const next = [
        conversation,
        ...prev.filter((item) => item.id !== conversation.id),
      ];
      return next.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    });
    await saveImageConversation(conversationScope, conversation);
  };

  const updateConversation = async (
    conversationId: string,
    updater: (current: ImageConversation | null) => ImageConversation,
  ) => {
    if (!conversationScope) {
      return;
    }
    const current =
      conversationsRef.current.find((item) => item.id === conversationId) ??
      null;
    const nextConversation = updater(current);
    conversationsRef.current = [
      nextConversation,
      ...conversationsRef.current.filter((item) => item.id !== conversationId),
    ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    setConversations(conversationsRef.current);

    await saveImageConversation(conversationScope, nextConversation);
  };

  const handleCreateDraft = () => {
    const clientConversationId = createClientRequestId("conv-");
    setSelectedConversationId(null);
    setPreviewImageId(null);
    setImagePrompt("");
    setInputImage(null);
    setInputImage(null);
    textareaRef.current?.focus();
    void Promise.resolve().then(() => {
      setInputImage(null);
    });
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    setSelectedConversationId((prev) => (prev === id ? null : prev));
    if (selectedConversationId === id) {
      setPreviewImageId(null);
    }

    try {
      if (!conversationScope) {
        return;
      }
      await deleteImageConversation(conversationScope, id);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除会话失败";
      toast.error(message);
      const items = conversationScope
        ? await listImageConversations(conversationScope)
        : [];
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      if (!conversationScope) {
        return;
      }
      await clearImageConversations(conversationScope);
      conversationsRef.current = [];
      setConversations([]);
      setSelectedConversationId(null);
      setPreviewImageId(null);
      toast.success("已清空历史记录");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "清空历史记录失败";
      toast.error(message);
    }
  };

  const handleGenerateImage = async () => {
    if (!conversationScope) {
      toast.error("当前登录信息还在初始化，请稍后再试");
      return;
    }
    const prompt = imagePrompt.trim();
    const currentInputImage = inputImage;
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }
    if (isQuotaInsufficient) {
      toast.error(`当前额度不足，本次需要 ${requestCost} 额度`);
      return;
    }

    const now = new Date().toISOString();
    const conversationId = currentInputImage?.clientConversationId || createClientRequestId("conv-");
    const queueRequestId = createClientRequestId("queue-");
    const draftInputImage: StoredInputImage | null = currentInputImage
      ? {
          id: currentInputImage.id,
          fileId: currentInputImage.fileId,
          fileName: currentInputImage.fileName,
          dataUrl: currentInputImage.dataUrl,
          clientConversationId: conversationId,
          mimeType: currentInputImage.dataUrl.startsWith("data:")
            ? currentInputImage.dataUrl.slice(5).split(";", 1)[0].trim() ||
              "image/png"
            : "image/png",
          sizeBytes: currentInputImage.sizeBytes,
        }
      : null;
    const draftConversation: ImageConversation = {
      id: conversationId,
      clientConversationId: conversationId,
      title: buildConversationTitle(prompt),
      prompt,
      model: imageModel,
      count: parsedCount,
      copiedText: undefined,
      inputImage: draftInputImage,
      images: Array.from({ length: parsedCount }, (_, index) => ({
        id: `${conversationId}-${index}`,
        status: "loading" as const,
      })),
      createdAt: now,
      status: "queued",
      queueRequestId,
      requestStartedAt: now,
    };
    const activeGenerationKey = `${conversationScope}:${conversationId}`;
    setQueueTitles((prev) => ({
      ...prev,
      [queueRequestId]: draftConversation.title,
    }));

    setSelectedConversationId(conversationId);
    setImagePrompt("");
    setInputImage(null);

    try {
      activeGenerationKeys.add(activeGenerationKey);
      await persistConversation(draftConversation);

      const data = await generateImage(prompt, imageModel, parsedCount, {
        inputImageUrl: currentInputImage?.dataUrl,
        inputImageFileId: currentInputImage?.fileId,
        queueRequestId,
        clientConversationId: conversationId,
      });
      const returnedItems = Array.isArray(data.data) ? data.data : [];
      if (data.billing) {
        setAvailableQuota(
          Math.max(0, Number(data.billing.remaining_quota || 0)),
        );
      }
      const nextImages: StoredImage[] = Array.from(
        { length: parsedCount },
        (_, index) => {
          const current = returnedItems[index];
          if (current?.b64_json) {
            return {
              id: `${conversationId}-${index}`,
              status: "success",
              b64_json: current.b64_json,
              mimeType:
                String(current.mime_type || "").trim() ||
                detectImageMimeType(current.b64_json),
            };
          }
          return {
            id: `${conversationId}-${index}`,
            status: "error",
            error: `第 ${index + 1} 张没有返回图片数据`,
          };
        },
      );

      const successCount = nextImages.filter(
        (item) => item.status === "success",
      ).length;
      const failedCount = nextImages.length - successCount;

      if (successCount === 0) {
        throw new Error("生成图片失败");
      }

      await updateConversation(conversationId, (current) => ({
        ...(current ?? draftConversation),
        copiedText: String(data.copied_text || "").trim() || undefined,
        images: nextImages,
        status: failedCount > 0 ? "error" : "success",
        error: failedCount > 0 ? `其中 ${failedCount} 张生成失败` : undefined,
        lastError: failedCount > 0 ? `其中 ${failedCount} 张生成失败` : undefined,
        requestFinishedAt: new Date().toISOString(),
      }));
      await loadQuota();

      if (failedCount > 0) {
        toast.error(
          `已完成 ${successCount} 张，另有 ${failedCount} 张未生成成功`,
        );
      } else {
        toast.success(`已生成 ${successCount} 张图片`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "生成图片失败";
      await persistConversation({
        ...draftConversation,
        status: "error",
        error: message,
        lastError: message,
        requestFinishedAt: new Date().toISOString(),
      });
      toast.error(message);
    } finally {
      activeGenerationKeys.delete(activeGenerationKey);
    }
  };

  const handleOpenInputImagePicker = () => {
    inputImageRef.current?.click();
  };

  const handleRemoveInputImage = () => {
    setInputImage(null);
    if (inputImageRef.current) {
      inputImageRef.current.value = "";
    }
  };

  const handleInputImageChange = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    if (!String(file.type || "").startsWith("image/")) {
      toast.error("只支持上传图片文件");
      return;
    }
    if (file.size > MAX_INPUT_IMAGE_BYTES) {
      toast.error("图片不能超过 8 MB");
      return;
    }
    try {
      setIsUploadingInputImage(true);
      const [dataUrl, uploadedImage] = await Promise.all([
        readFileAsDataUrl(file),
        uploadInputImage(file, inputImage?.clientConversationId || createClientRequestId("conv-")),
      ]);
      const clientConversationId =
        String(uploadedImage.client_conversation_id || "").trim() ||
        inputImage?.clientConversationId ||
        createClientRequestId("conv-");
      const imageId =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      setInputImage({
        id: imageId,
        fileId: uploadedImage.file_id,
        fileName: file.name,
        dataUrl,
        sizeBytes: file.size,
        clientConversationId,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取图片失败";
      toast.error(message);
    } finally {
      setIsUploadingInputImage(false);
    }
  };

  const handleOpenPreview = (imageId: string) => {
    setPreviewImageId(imageId);
  };

  const handlePreviewStep = (step: -1 | 1) => {
    if (previewImageIndex < 0) {
      return;
    }
    const nextIndex = previewImageIndex + step;
    if (nextIndex < 0 || nextIndex >= previewableImages.length) {
      return;
    }
    setPreviewImageId(previewableImages[nextIndex]?.id ?? null);
  };

  const handleDownloadPreviewImage = () => {
    if (!previewImage) {
      return;
    }
    const ext = detectImageFileExtension(
      previewImage.b64Json,
      previewImage.mimeType,
    );
    downloadBase64Image(
      previewImage.b64Json,
      `image-${Date.now()}-${previewImageIndex + 1}.${ext}`,
      previewImage.mimeType,
    );
  };

  return (
    <>
      <section className="minimal-page-shell minimal-image-shell minimal-fade-soft mx-auto grid min-h-0 w-full max-w-[1400px] grid-cols-1 gap-3 px-0 pb-3 sm:px-1 sm:pb-4 lg:h-[calc(100vh-5rem)] lg:grid-cols-[300px_minmax(0,1fr)] lg:gap-5 lg:px-2 lg:pb-6">
        <aside className="minimal-fade-soft order-2 min-h-0 [animation-delay:60ms] lg:order-1">
          <div className="flex h-auto min-h-0 flex-col gap-3 py-1 sm:py-2 lg:h-full">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:flex sm:flex-row">
              <Button className="h-11 flex-1" onClick={handleCreateDraft}>
                <MessageSquarePlus className="size-4" />
                新建对话
              </Button>
              <Button
                variant="outline"
                className="h-11 px-3 sm:w-auto"
                onClick={() => void handleClearHistory()}
                disabled={conversations.length === 0}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>

            <div className="minimal-fade-soft flex min-h-0 flex-col border-t border-white/8 pt-4 [animation-delay:120ms] lg:flex-1">
              <div className="space-y-2 text-xs text-stone-500">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">当前模型</span>
                  <span className="font-medium text-stone-900">
                    {imageModel}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">剩余额度</span>
                  <span className="font-medium text-stone-900">
                    {availableQuotaLabel}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">本次消耗</span>
                  <span className="font-medium text-stone-900">
                    {requestCost} 额度
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">当前队列</span>
                  <span className="font-medium text-stone-900">
                    {queueStatus
                      ? `${queueStatus.user.waiting} 等待 / ${queueStatus.user.running} 运行`
                      : "加载中"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">当前请求</span>
                  <span className="text-right font-medium text-stone-900">
                    {currentQueueRequest?.position
                      ? `第 ${currentQueueRequest.position} 位`
                      : currentQueueRequest
                        ? formatQueueStatusBadge(currentQueueRequest)
                        : "空闲"}
                  </span>
                </div>
              </div>
              <p className="mt-4 text-[11px] leading-5 text-stone-400">
                当前单价 {currentUnitCost} 额度 / 张
              </p>
              <p className="mt-2 text-[11px] leading-5 text-stone-400">
                {currentQueueProgressText}
              </p>

              <div className="mt-5 border-t border-white/8 pt-4">
                {activeQueueItems.length === 0 ? (
                  <div className="text-sm leading-6 text-stone-500">
                    当前没有等待中的请求
                  </div>
                ) : (
                  <div className="space-y-2">
                    {activeQueueItems.map((item) => (
                      <div
                        key={item.request_id}
                        className="flex items-start justify-between gap-3 border-l border-stone-300/40 pl-3 text-sm text-stone-700"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-medium text-stone-900">
                            {formatQueueItemLabel(item, queueTitles)}
                          </div>
                          <div className="mt-1 text-xs leading-5 text-stone-500">
                            {formatQueueProgressText(item)}
                          </div>
                        </div>
                        <div className="shrink-0 text-[11px] text-stone-500">
                          {formatQueueStatusBadge(item)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="mt-5 min-h-0 border-t border-white/8 pt-4 lg:flex-1 lg:overflow-y-auto lg:pr-1">
                {isLoadingHistory ? (
                  <div className="flex items-center gap-2 py-3 text-sm text-stone-500">
                    <LoaderCircle className="size-4 animate-spin" />
                    正在读取会话记录
                  </div>
                ) : conversations.length === 0 ? (
                  <div className="py-3 text-sm leading-6 text-stone-500">
                    {activeQueueItems.length === 0 ? "暂无记录" : ""}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {conversations.map((conversation) => {
                      const active = conversation.id === selectedConversationId;
                      return (
                        <div
                          key={conversation.id}
                          className={cn(
                            "minimal-row-shift group relative w-full border-l-2 px-3 py-3 text-left transition",
                            active
                              ? "border-stone-900 bg-black/[0.03] text-stone-950"
                              : "border-transparent text-stone-700 hover:border-stone-300 hover:bg-white/40",
                          )}
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedConversationId(conversation.id)
                            }
                            className="block w-full pr-8 text-left"
                          >
                            <div className="truncate text-sm font-semibold">
                              {conversation.title}
                            </div>
                            <div
                              className={cn(
                                "mt-1 text-xs",
                                active ? "text-stone-500" : "text-stone-400",
                              )}
                            >
                              {formatConversationTime(conversation.createdAt)}
                            </div>
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              void handleDeleteConversation(conversation.id)
                            }
                            className="absolute top-3 right-2 inline-flex size-7 items-center justify-center rounded-md text-stone-400 opacity-100 transition hover:bg-stone-100 hover:text-rose-500 lg:opacity-0 lg:group-hover:opacity-100"
                            aria-label="删除会话"
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </aside>

        <div className="order-1 flex min-h-0 flex-col gap-4 xl:order-2">
          <div
            ref={resultsViewportRef}
            className="hide-scrollbar overflow-visible px-1 py-2 sm:px-3 sm:py-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto"
          >
            {!selectedConversation ? (
              <div className="flex min-h-[240px] items-center justify-center px-1 text-center sm:min-h-[360px] lg:h-full lg:min-h-[420px]">
                <div className="minimal-fade-up w-full max-w-4xl px-4 py-8 sm:py-10">
                  <div className="minimal-kicker justify-center">
                    image workstation
                  </div>
                  <h1 className="minimal-heading mt-5 text-3xl sm:text-4xl md:text-6xl">
                    生成图片
                  </h1>
                  <p className="minimal-fade-soft mt-4 text-sm text-white/62 sm:mt-5 sm:text-[15px] [animation-delay:120ms]">
                    输入提示词即可开始。
                  </p>
                </div>
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-[980px] flex-col gap-5">
                <div className="flex justify-end">
                  <div className="flex max-w-full flex-col items-end gap-3 sm:max-w-[80%]">
                    {selectedConversation.inputImage ? (
                      <div className="minimal-surface-hover minimal-fade-soft overflow-hidden rounded-[18px] border border-stone-200 bg-white shadow-sm">
                        <img
                          src={selectedConversation.inputImage.dataUrl}
                          alt={
                            selectedConversation.inputImage.fileName || "参考图"
                          }
                          className="block h-28 w-28 object-cover"
                        />
                        <div className="border-t border-stone-100 px-3 py-2 text-[11px] text-stone-500">
                          {selectedConversation.inputImage.fileName || "参考图"}
                        </div>
                      </div>
                    ) : null}
                    <div className="px-1 pt-1 text-right text-sm leading-7 text-stone-700 sm:text-[15px] sm:leading-8">
                      {selectedConversation.prompt}
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500">
                    <span className="rounded-full bg-stone-100 px-3 py-1">
                      {selectedConversation.model}
                    </span>
                    <span className="rounded-full bg-stone-100 px-3 py-1">
                      {selectedConversation.count} 张
                    </span>
                    <span className="rounded-full bg-stone-100 px-3 py-1">
                      {formatConversationTime(selectedConversation.createdAt)}
                    </span>
                  </div>

                  {selectedConversation.status === "generating" ? (
                    <div className="minimal-surface-hover minimal-fade-soft rounded-[20px] border border-stone-200 bg-stone-50/90 px-4 py-4">
                      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-stone-400">
                        <LoaderCircle className="size-4 animate-spin" />
                        排队进度
                      </div>
                      <div className="mt-3 text-sm leading-6 text-stone-700">
                        {currentQueueProgressText}
                      </div>
                    </div>
                  ) : null}

                  {selectedConversation.copiedText ? (
                    <div className="minimal-surface-hover minimal-fade-soft rounded-[20px] border border-stone-200 bg-stone-50/80 px-4 py-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-xs font-medium uppercase tracking-[0.16em] text-stone-400">
                          可复制文本
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 rounded-full border-stone-200 bg-white text-stone-600 hover:bg-stone-100"
                          onClick={() => {
                            void navigator.clipboard.writeText(
                              selectedConversation.copiedText || "",
                            );
                            toast.success("文本已复制");
                          }}
                        >
                          <Copy className="size-4" />
                          复制
                        </Button>
                      </div>
                      <pre className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-stone-700">
                        {selectedConversation.copiedText}
                      </pre>
                    </div>
                  ) : null}

                  {selectedConversation.status === "error" &&
                  selectedConversation.images.length === 0 ? (
                    <div className="border-l-2 border-rose-300 bg-rose-50/70 px-4 py-4 text-sm leading-6 text-rose-600">
                      {selectedConversation.error || "生成失败"}
                    </div>
                  ) : null}

                  {selectedConversation.images.length > 0 ? (
                    <div className="columns-1 gap-4 space-y-4 sm:columns-2 xl:columns-3">
                      {selectedConversation.images.map((image, index) => (
                        <div
                          key={image.id}
                          className="minimal-fade-soft break-inside-avoid overflow-hidden rounded-[22px]"
                        >
                          {image.status === "success" && image.b64_json ? (
                            <button
                              type="button"
                              onClick={() => handleOpenPreview(image.id)}
                              className="minimal-surface-hover group block w-full overflow-hidden rounded-[22px] bg-stone-100 text-left"
                              aria-label={`预览第 ${index + 1} 张图片`}
                            >
                              <img
                                src={buildImageDataUrl(
                                  image.b64_json,
                                  image.mimeType,
                                )}
                                alt={`Generated result ${index + 1}`}
                                loading="lazy"
                                className="block h-auto w-full transition duration-200 group-hover:scale-[1.01]"
                              />
                            </button>
                          ) : image.status === "error" ? (
                            <div className="flex min-h-[320px] items-center justify-center bg-rose-50 px-6 py-8 text-center text-sm leading-6 text-rose-600">
                              {image.error || "生成失败"}
                            </div>
                          ) : (
                            <div className="flex min-h-[320px] flex-col items-center justify-center gap-3 bg-stone-100/80 px-6 py-8 text-center text-stone-500">
                              <div className="rounded-full bg-white p-3 shadow-sm">
                                <LoaderCircle className="size-5 animate-spin" />
                              </div>
                              <p className="text-sm">正在生成图片...</p>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {selectedConversation.status === "error" &&
                  selectedConversation.images.length > 0 ? (
                    <div className="border-l-2 border-amber-300 bg-amber-50/70 px-4 py-3 text-sm leading-6 text-amber-700">
                      {selectedConversation.error}
                    </div>
                  ) : null}
                </div>
              </div>
            )}
          </div>

          <div className="shrink-0 flex justify-center">
            <div
              className="image-composer minimal-fade-up max-h-[45dvh] w-full max-w-[980px] overflow-y-auto rounded-[28px] border border-white/12 bg-[#121218]/95 p-3 shadow-[0_22px_65px_-42px_rgba(0,0,0,0.95)] backdrop-blur-xl transition duration-200 focus-within:border-amber-300/45 focus-within:shadow-[0_0_0_1px_rgba(245,158,11,0.12),0_22px_70px_-44px_rgba(245,158,11,0.45)] sm:p-4 [animation-delay:220ms]"
              onClick={() => {
                textareaRef.current?.focus();
              }}
            >
              <input
                ref={inputImageRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,image/avif"
                className="hidden"
                onChange={(event) => {
                  void handleInputImageChange(event);
                }}
              />
              {inputImage ? (
                <div className="minimal-fade-soft mb-3 flex items-start gap-3 rounded-[18px] border border-white/8 bg-black/10 px-3 py-3">
                  <img
                    src={inputImage.dataUrl}
                    alt={inputImage.fileName}
                    className="size-14 shrink-0 rounded-xl object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-stone-100">
                      {inputImage.fileName}
                    </div>
                    <div className="mt-1 text-xs text-stone-400">
                      已附加 1 张参考图
                      {" · "}
                      {formatInputImageSize(inputImage.sizeBytes)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      handleRemoveInputImage();
                    }}
                    className="inline-flex size-8 items-center justify-center rounded-full text-stone-400 transition hover:bg-white/10 hover:text-stone-100"
                    aria-label="移除已上传图片"
                  >
                    <X className="size-4" />
                  </button>
                </div>
              ) : null}
              <label htmlFor="image-prompt" className="sr-only">
                输入你想要生成的画面
              </label>
              <Textarea
                id="image-prompt"
                ref={textareaRef}
                value={imagePrompt}
                onChange={(event) => setImagePrompt(event.target.value)}
                rows={1}
                placeholder="输入你想要生成的画面"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    if (
                      !isComposerGenerating &&
                      !isQuotaInsufficient &&
                      !isUploadingInputImage
                    ) {
                      void handleGenerateImage();
                    }
                  }
                }}
                className="h-auto min-h-0 w-full resize-none overflow-y-hidden rounded-none border-0 bg-transparent px-1 py-2 text-sm leading-6 text-stone-100 shadow-none placeholder:text-stone-500 focus-visible:ring-0 sm:px-2 sm:py-3 sm:text-[15px] sm:leading-7"
              />

              <div className="mt-2 flex flex-col gap-3 border-t border-white/8 pt-3">
                <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-10 rounded-full border-white/10 bg-white/[0.04] px-4 text-stone-200 hover:bg-white/[0.08]"
                    asChild
                  >
                    <Link href="/gallery">
                      <Images className="size-4" />
                      打开画廊
                    </Link>
                  </Button>

                  <button
                    type="button"
                    onClick={handleOpenInputImagePicker}
                    disabled={isUploadingInputImage}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/40",
                      inputImage
                        ? "border-amber-300/25 bg-amber-300/12 text-amber-100"
                        : "border-white/10 bg-white/[0.04] text-stone-300 hover:border-white/18 hover:text-stone-100",
                      isUploadingInputImage
                        ? "cursor-not-allowed opacity-60"
                        : "",
                    )}
                  >
                    {isUploadingInputImage ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <ImagePlus className="size-4" />
                    )}
                    {isUploadingInputImage
                      ? "上传中"
                      : inputImage
                        ? "更换图片"
                        : "上传图片"}
                  </button>

                  {(
                    Object.entries(imageModelMeta) as Array<
                      [ImageModel, (typeof imageModelMeta)[ImageModel]]
                    >
                  )
                    .filter(([model]) => model === "gpt-image-2")
                    .map(([model]) => {
                      const active = imageModel === model;
                      return (
                        <button
                          key={model}
                          type="button"
                          aria-pressed={active}
                          onClick={() => setImageModel(model)}
                          className={cn(
                            "cursor-pointer rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/40",
                            active
                              ? "border-white/15 bg-white/14 text-white"
                              : "border-white/10 bg-white/[0.04] text-stone-300 hover:border-white/18 hover:text-stone-100",
                          )}
                        >
                          {model}
                        </button>
                      );
                    })}

                  {IMAGE_COUNT_OPTIONS.map((count) => {
                    const active = imageCount === count;
                    return (
                      <button
                        key={count}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setImageCount(count)}
                        className={cn(
                          "cursor-pointer rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300/40",
                          active
                            ? "border-white/15 bg-white/14 text-white"
                            : "border-white/10 bg-white/[0.04] text-stone-300 hover:border-white/18 hover:text-stone-100",
                        )}
                      >
                        {count} 张
                      </button>
                    );
                  })}

                  <div className="ml-auto">
                    <Button
                      type="button"
                      onClick={() => void handleGenerateImage()}
                      disabled={
                        isComposerGenerating ||
                        isQuotaInsufficient ||
                        isUploadingInputImage
                      }
                      className="size-11 rounded-full bg-stone-50 p-0 text-stone-950 hover:bg-white disabled:bg-white/20 disabled:text-stone-500"
                      aria-label="发送"
                    >
                      {isComposerGenerating ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <ArrowUp className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>

                <div
                  className={cn(
                    "mt-3 text-xs",
                    isQuotaInsufficient ? "text-rose-400" : "text-stone-400",
                  )}
                >
                  {isQuotaInsufficient
                    ? `至少需要 ${requestCost} 额度`
                    : isUploadingInputImage
                      ? "图片上传中"
                      : inputImage
                        ? "已附加 1 张参考图，回车发送"
                        : "回车发送"}
                </div>
              </div>
            </div>
          </div>
        </div>

      </section>

      <Dialog
        open={Boolean(previewImage)}
        onOpenChange={(open) => (!open ? setPreviewImageId(null) : null)}
      >
        <DialogContent className="w-[min(96vw,1120px)] bg-[rgba(10,10,15,0.96)] p-2 sm:p-4">
          {previewImage ? (
            <div className="space-y-3">
              <div className="flex flex-col gap-3 rounded-[18px] bg-white/6 px-3 py-2 text-sm text-stone-200 sm:flex-row sm:items-center sm:justify-between sm:px-4">
                <div className="flex items-center gap-2 text-stone-300">
                  <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium">
                    {previewImageIndex + 1} / {previewableImages.length}
                  </span>
                  <span className="hidden text-xs text-stone-400 sm:inline">
                    当前会话成功图片预览
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleDownloadPreviewImage}
                    className="border-white/15 bg-white/8 text-stone-100 hover:bg-white/14"
                  >
                    <Download className="size-4" />
                    下载
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handlePreviewStep(-1)}
                    disabled={!hasPreviousPreviewImage}
                    className="border-white/15 bg-white/8 text-stone-100 hover:bg-white/14"
                  >
                    <ArrowLeft className="size-4" />
                    上一张
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handlePreviewStep(1)}
                    disabled={!hasNextPreviewImage}
                    className="border-white/15 bg-white/8 text-stone-100 hover:bg-white/14"
                  >
                    下一张
                    <ArrowRight className="size-4" />
                  </Button>
                </div>
              </div>

              <div className="flex items-center justify-center overflow-hidden rounded-[20px] bg-black/60">
                <img
                  src={previewImage.src}
                  alt={previewImage.alt}
                  className="h-auto max-h-[82vh] w-auto max-w-full object-contain"
                />
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
