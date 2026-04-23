"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { ArrowLeft, ArrowRight, ArrowUp, Copy, Download, ImagePlus, LoaderCircle, MessageSquarePlus, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { buildImageDataUrl, detectImageFileExtension, detectImageMimeType } from "@/lib/image-data";
import { Textarea } from "@/components/ui/textarea";
import { fetchQuotaSummary, generateImage, type ImageModel } from "@/lib/api";
import {
  clearImageConversations,
  deleteImageConversation,
  listImageConversations,
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
const IMAGE_COUNT_OPTIONS = Array.from({ length: MAX_IMAGES_PER_REQUEST }, (_, index) => String(index + 1));
const MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024;

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

function downloadBase64Image(base64: string, fileName: string, mimeType?: string) {
  const binary = window.atob(base64);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const resolvedMimeType = String(mimeType || "").trim() || detectImageMimeType(base64);
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
  fileName: string;
  dataUrl: string;
  sizeBytes: number;
};

function formatInputImageSize(sizeBytes: number) {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`;
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

async function normalizeConversationHistory(items: ImageConversation[], scope: string) {
  const normalized = items.map((item) =>
    item.status === "generating"
      ? {
          ...item,
          status: "error" as const,
          error: item.images.some((image) => image.status === "success")
            ? item.error || "生成已中断"
            : "页面已刷新，生成已中断",
          images: item.images.map((image) =>
            image.status === "loading"
              ? {
                  ...image,
                  status: "error" as const,
                  error: "页面已刷新，生成已中断",
                }
              : image,
          ),
        }
      : item,
  );

  await Promise.all(
    normalized
      .filter((item, index) => item !== items[index])
      .map((item) => saveImageConversation(scope, item)),
  );

  return normalized;
}

export default function ImagePage() {
  const didLoadQuotaRef = useRef(false);
  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageModel, setImageModel] = useState<ImageModel>("gpt-image-2");
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [conversationScope, setConversationScope] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [inputImage, setInputImage] = useState<PendingInputImage | null>(null);
  const [availableQuota, setAvailableQuota] = useState<number | null>(null);
  const [currentPricing, setCurrentPricing] = useState<Record<ImageModel, number> | null>(null);
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputImageRef = useRef<HTMLInputElement>(null);

  const parsedCount = useMemo(
    () => Math.max(1, Math.min(MAX_IMAGES_PER_REQUEST, Number(imageCount) || 1)),
    [imageCount],
  );
  const effectivePricing = useMemo(
    () => currentPricing || DEFAULT_IMAGE_PRICING,
    [currentPricing],
  );
  const currentUnitCost = useMemo(() => Math.max(0, Number(effectivePricing[imageModel] || 0)), [effectivePricing, imageModel]);
  const requestCost = useMemo(() => parsedCount * currentUnitCost, [currentUnitCost, parsedCount]);
  const isQuotaInsufficient = useMemo(
    () => availableQuota !== null && requestCost > Math.max(0, availableQuota),
    [availableQuota, requestCost],
  );
  const availableQuotaLabel = availableQuota === null ? "加载中" : String(Math.max(0, availableQuota));
  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
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
                mimeType: String(image.mimeType || "").trim() || detectImageMimeType(image.b64_json),
              },
            ]
          : [],
      ),
    [selectedConversation],
  );
  const activePreviewImageId = useMemo(
    () => (previewableImages.some((image) => image.id === previewImageId) ? previewImageId : null),
    [previewImageId, previewableImages],
  );
  const previewImageIndex = useMemo(
    () => previewableImages.findIndex((image) => image.id === activePreviewImageId),
    [activePreviewImageId, previewableImages],
  );
  const previewImage = previewImageIndex >= 0 ? previewableImages[previewImageIndex] : null;
  const hasPreviousPreviewImage = previewImageIndex > 0;
  const hasNextPreviewImage = previewImageIndex >= 0 && previewImageIndex < previewableImages.length - 1;

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
        const normalizedItems = await normalizeConversationHistory(items, conversationScope);
        if (cancelled) {
          return;
        }
        setConversations(normalizedItems);
      } catch (error) {
        const message = error instanceof Error ? error.message : "读取会话记录失败";
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
      window.removeEventListener("chatgpt2api:quota-changed", handleQuotaChanged);
    };
  }, [loadQuota]);

  useEffect(() => {
    if (!selectedConversation && !isGenerating) {
      return;
    }

    resultsViewportRef.current?.scrollTo({
      top: resultsViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation, isGenerating]);

  const persistConversation = async (conversation: ImageConversation) => {
    if (!conversationScope) {
      return;
    }
    setConversations((prev) => {
      const next = [conversation, ...prev.filter((item) => item.id !== conversation.id)];
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
    let nextConversation: ImageConversation | null = null;

    setConversations((prev) => {
      const current = prev.find((item) => item.id === conversationId) ?? null;
      nextConversation = updater(current);
      const next = [nextConversation, ...prev.filter((item) => item.id !== conversationId)];
      return next.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    });

    if (nextConversation) {
      await saveImageConversation(conversationScope, nextConversation);
    }
  };

  const handleCreateDraft = () => {
    setSelectedConversationId(null);
    setPreviewImageId(null);
    setImagePrompt("");
    setInputImage(null);
    textareaRef.current?.focus();
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
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
      const items = conversationScope ? await listImageConversations(conversationScope) : [];
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      if (!conversationScope) {
        return;
      }
      await clearImageConversations(conversationScope);
      setConversations([]);
      setSelectedConversationId(null);
      setPreviewImageId(null);
      toast.success("已清空历史记录");
    } catch (error) {
      const message = error instanceof Error ? error.message : "清空历史记录失败";
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
      toast.error(`当前额度不足，本次需要 ${requestCost} 次`);
      return;
    }

    const now = new Date().toISOString();
    const conversationId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const draftInputImage: StoredInputImage | null = currentInputImage
      ? {
          id: currentInputImage.id,
          fileName: currentInputImage.fileName,
          dataUrl: currentInputImage.dataUrl,
          mimeType: currentInputImage.dataUrl.startsWith("data:")
            ? currentInputImage.dataUrl.slice(5).split(";", 1)[0].trim() || "image/png"
            : "image/png",
          sizeBytes: currentInputImage.sizeBytes,
        }
      : null;
    const draftConversation: ImageConversation = {
      id: conversationId,
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
      status: "generating",
    };

    setIsGenerating(true);
    setSelectedConversationId(conversationId);
    setImagePrompt("");
    setInputImage(null);

    try {
      await persistConversation(draftConversation);

      const data = await generateImage(prompt, imageModel, parsedCount, {
        inputImageUrl: currentInputImage?.dataUrl,
      });
      const returnedItems = Array.isArray(data.data) ? data.data : [];
      if (data.billing) {
        setAvailableQuota(Math.max(0, Number(data.billing.remaining_quota || 0)));
      }
      const nextImages: StoredImage[] = Array.from({ length: parsedCount }, (_, index) => {
        const current = returnedItems[index];
        if (current?.b64_json) {
          return {
            id: `${conversationId}-${index}`,
            status: "success",
            b64_json: current.b64_json,
            mimeType: String(current.mime_type || "").trim() || detectImageMimeType(current.b64_json),
          };
        }
        return {
          id: `${conversationId}-${index}`,
          status: "error",
          error: `第 ${index + 1} 张没有返回图片数据`,
        };
      });

      const successCount = nextImages.filter((item) => item.status === "success").length;
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
      }));
      await loadQuota();

      if (failedCount > 0) {
        toast.error(`已完成 ${successCount} 张，另有 ${failedCount} 张未生成成功`);
      } else {
        toast.success(`已生成 ${successCount} 张图片`);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "生成图片失败";
      await persistConversation({
        ...draftConversation,
        status: "error",
        error: message,
      });
      toast.error(message);
    } finally {
      setIsGenerating(false);
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

  const handleInputImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
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
      const dataUrl = await readFileAsDataUrl(file);
      const imageId =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      setInputImage({
        id: imageId,
        fileName: file.name,
        dataUrl,
        sizeBytes: file.size,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取图片失败";
      toast.error(message);
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
    const ext = detectImageFileExtension(previewImage.b64Json, previewImage.mimeType);
    downloadBase64Image(
      previewImage.b64Json,
      `image-${Date.now()}-${previewImageIndex + 1}.${ext}`,
      previewImage.mimeType,
    );
  };

  return (
    <>
      <section className="mx-auto grid h-[calc(100vh-5rem)] min-h-0 w-full max-w-[1380px] grid-cols-1 gap-3 px-3 pb-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="min-h-0 border-r border-stone-200/70 pr-3">
          <div className="flex h-full min-h-0 flex-col gap-3 py-2">
            <div className="flex items-center gap-2">
              <Button
                className="h-10 flex-1 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                onClick={handleCreateDraft}
              >
                <MessageSquarePlus className="size-4" />
                新建对话
              </Button>
              <Button
                variant="outline"
                className="h-10 rounded-xl border-stone-200 bg-white/85 px-3 text-stone-600 hover:bg-white"
                onClick={() => void handleClearHistory()}
                disabled={conversations.length === 0}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>

            <div className="rounded-[22px] border border-stone-200/80 bg-white px-4 py-4 shadow-[0_12px_30px_rgba(0,0,0,0.03)]">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">生成信息</div>
              <div className="mt-4 space-y-2 text-xs text-stone-500">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">当前模型</span>
                  <span className="font-medium text-stone-900">{imageModel}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">剩余额度</span>
                  <span className="font-medium text-stone-900">{availableQuotaLabel}</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-stone-400">本次消耗</span>
                  <span className="font-medium text-stone-900">{requestCost} 次</span>
                </div>
              </div>
              <p className="mt-4 text-[11px] leading-5 text-stone-400">{currentUnitCost} / 张</p>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-stone-400">对话记录</div>
              <div className="space-y-2">
              {isLoadingHistory ? (
                <div className="flex items-center gap-2 px-2 py-3 text-sm text-stone-500">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取会话记录
                </div>
              ) : conversations.length === 0 ? (
                <div className="px-2 py-3 text-sm leading-6 text-stone-500">
                  暂无记录
                </div>
              ) : (
                conversations.map((conversation) => {
                  const active = conversation.id === selectedConversationId;
                  return (
                    <div
                      key={conversation.id}
                      className={cn(
                        "group relative w-full border-l-2 px-3 py-3 text-left transition",
                        active
                          ? "border-stone-900 bg-black/[0.03] text-stone-950"
                          : "border-transparent text-stone-700 hover:border-stone-300 hover:bg-white/40",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedConversationId(conversation.id)}
                        className="block w-full pr-8 text-left"
                      >
                        <div className="truncate text-sm font-semibold">{conversation.title}</div>
                        <div className={cn("mt-1 text-xs", active ? "text-stone-500" : "text-stone-400")}>
                          {formatConversationTime(conversation.createdAt)}
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDeleteConversation(conversation.id)}
                        className="absolute top-3 right-2 inline-flex size-7 items-center justify-center rounded-md text-stone-400 opacity-0 transition hover:bg-stone-100 hover:text-rose-500 group-hover:opacity-100"
                        aria-label="删除会话"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  );
                })
              )}
              </div>
            </div>
          </div>
        </aside>

        <div className="flex min-h-0 flex-col gap-4">
          <div
            ref={resultsViewportRef}
            className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-2 py-3 sm:px-4 sm:py-4"
          >
            {!selectedConversation ? (
              <div className="flex h-full min-h-[420px] items-center justify-center text-center">
                <div className="w-full max-w-4xl">
                  <h1 className="text-3xl font-semibold tracking-tight text-stone-950 md:text-5xl">生成图片</h1>
                  <p className="mt-4 text-[15px] text-stone-500">输入提示词即可开始。</p>
                </div>
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-[980px] flex-col gap-5">
                <div className="flex justify-end">
                  <div className="flex max-w-[80%] flex-col items-end gap-3">
                    {selectedConversation.inputImage ? (
                      <div className="overflow-hidden rounded-[18px] border border-stone-200 bg-white shadow-sm">
                        <img
                          src={selectedConversation.inputImage.dataUrl}
                          alt={selectedConversation.inputImage.fileName || "参考图"}
                          className="block h-28 w-28 object-cover"
                        />
                        <div className="border-t border-stone-100 px-3 py-2 text-[11px] text-stone-500">
                          {selectedConversation.inputImage.fileName || "参考图"}
                        </div>
                      </div>
                    ) : null}
                    <div className="px-1 pt-1 text-right text-[15px] leading-8 text-stone-700">
                      {selectedConversation.prompt}
                    </div>
                  </div>
                </div>

                <div className="flex justify-start">
                  <div className="w-full p-1">
                    <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-stone-500">
                      <span className="rounded-full bg-stone-100 px-3 py-1">{selectedConversation.model}</span>
                      <span className="rounded-full bg-stone-100 px-3 py-1">{selectedConversation.count} 张</span>
                      <span className="rounded-full bg-stone-100 px-3 py-1">
                        {formatConversationTime(selectedConversation.createdAt)}
                      </span>
                    </div>

                    {selectedConversation.copiedText ? (
                      <div className="mb-4 rounded-[20px] border border-stone-200 bg-stone-50/80 px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-xs font-medium uppercase tracking-[0.16em] text-stone-400">可复制文本</div>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 rounded-full border-stone-200 bg-white text-stone-600 hover:bg-stone-100"
                            onClick={() => {
                              void navigator.clipboard.writeText(selectedConversation.copiedText || "");
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

                    {selectedConversation.status === "error" && selectedConversation.images.length === 0 ? (
                      <div className="border-l-2 border-rose-300 bg-rose-50/70 px-4 py-4 text-sm leading-6 text-rose-600">
                        {selectedConversation.error || "生成失败"}
                      </div>
                    ) : null}

                    {selectedConversation.images.length > 0 ? (
                      <div className="columns-1 gap-4 space-y-4 sm:columns-2 xl:columns-3">
                        {selectedConversation.images.map((image, index) => (
                          <div key={image.id} className="break-inside-avoid overflow-hidden rounded-[22px]">
                            {image.status === "success" && image.b64_json ? (
                              <button
                                type="button"
                                onClick={() => handleOpenPreview(image.id)}
                                className="group block w-full overflow-hidden rounded-[22px] bg-stone-100 text-left"
                                aria-label={`预览第 ${index + 1} 张图片`}
                              >
                                <img
                                  src={buildImageDataUrl(image.b64_json, image.mimeType)}
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

                    {selectedConversation.status === "error" && selectedConversation.images.length > 0 ? (
                      <div className="mt-4 border-l-2 border-amber-300 bg-amber-50/70 px-4 py-3 text-sm leading-6 text-amber-700">
                        {selectedConversation.error}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="shrink-0 flex justify-center">
            <div
              className="w-full max-w-[980px] rounded-[24px] border border-stone-200/80 bg-white shadow-[0_0.25rem_1.25rem_rgba(0,0,0,0.04),0_0_0_0.5px_rgba(214,211,209,0.52)] transition-shadow duration-200 hover:shadow-[0_0.25rem_1.25rem_rgba(0,0,0,0.06),0_0_0_0.5px_rgba(214,211,209,0.72)] focus-within:shadow-[0_0.25rem_1.25rem_rgba(0,0,0,0.08),0_0_0_0.5px_rgba(214,211,209,0.88)]"
            >
              <div
                className="cursor-text px-4 pt-4 pb-3 sm:px-5"
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
                <div className="flex min-h-[196px] flex-col rounded-[22px] border border-stone-200/70 bg-white">
                  {inputImage ? (
                    <div className="border-b border-stone-100 px-4 pt-4 pb-3">
                      <div className="flex items-center gap-3 rounded-2xl bg-stone-50 px-3 py-3">
                        <img
                          src={inputImage.dataUrl}
                          alt={inputImage.fileName}
                          className="size-14 shrink-0 rounded-xl object-cover"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-stone-900">{inputImage.fileName}</div>
                          <div className="mt-1 text-xs text-stone-500">
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
                          className="inline-flex size-8 items-center justify-center rounded-full text-stone-400 transition hover:bg-white hover:text-stone-700"
                          aria-label="移除已上传图片"
                        >
                          <X className="size-4" />
                        </button>
                      </div>
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
                    placeholder="输入你想要生成的画面"
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        if (!isGenerating && !isQuotaInsufficient) {
                          void handleGenerateImage();
                        }
                      }
                    }}
                    className="min-h-[136px] resize-none border-0 bg-transparent px-4 pt-4 pb-3 text-[15px] leading-7 text-stone-900 shadow-none placeholder:text-stone-400 focus-visible:ring-0"
                  />

                  <div className="mt-auto border-t border-stone-100 px-4 py-3">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div className="flex min-w-0 flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            onClick={handleOpenInputImagePicker}
                            className={cn(
                              "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-300",
                              inputImage
                                ? "border-stone-900 bg-stone-950 text-white"
                                : "border-stone-200 bg-white text-stone-700 hover:border-stone-300 hover:bg-stone-100",
                            )}
                          >
                            <ImagePlus className="size-4" />
                            {inputImage ? "更换图片" : "上传图片"}
                          </button>

                          <div className="h-4 w-px bg-stone-200" />

                          {(Object.entries(imageModelMeta) as Array<[ImageModel, (typeof imageModelMeta)[ImageModel]]>)
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
                                  "cursor-pointer rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-300",
                                  active
                                    ? "border-stone-900 bg-stone-950 text-white"
                                    : "border-stone-200 bg-white text-stone-700 hover:border-stone-300 hover:bg-stone-100",
                                )}
                              >
                                {model}
                              </button>
                            );
                          })}

                          <div className="h-4 w-px bg-stone-200" />

                          {IMAGE_COUNT_OPTIONS.map((count) => {
                            const active = imageCount === count;
                            return (
                              <button
                                key={count}
                                type="button"
                                aria-pressed={active}
                                onClick={() => setImageCount(count)}
                                className={cn(
                                  "cursor-pointer rounded-full border px-3 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-300",
                                  active
                                    ? "border-stone-900 bg-stone-900 text-white"
                                    : "border-stone-200 bg-stone-50 text-stone-600 hover:border-stone-300 hover:bg-stone-100",
                                )}
                              >
                                {count} 张
                              </button>
                            );
                          })}
                        </div>

                        <div className={cn("text-xs", isQuotaInsufficient ? "text-rose-600" : "text-stone-500")}>
                          {isQuotaInsufficient
                            ? `至少需要 ${requestCost} 次`
                            : inputImage
                              ? "已附加 1 张参考图，回车发送"
                              : "回车发送"}
                        </div>
                      </div>

                      <Button
                        type="button"
                        onClick={() => void handleGenerateImage()}
                        disabled={isGenerating || isQuotaInsufficient}
                        className="h-11 shrink-0 rounded-full bg-stone-950 px-4 text-sm font-medium text-white hover:bg-stone-800 disabled:bg-stone-300"
                      >
                        {isGenerating ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <Dialog open={Boolean(previewImage)} onOpenChange={(open) => (!open ? setPreviewImageId(null) : null)}>
        <DialogContent className="w-[min(96vw,1120px)] border-stone-800/80 bg-stone-950 p-2 sm:p-4">
          {previewImage ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3 rounded-[18px] bg-white/6 px-3 py-2 text-sm text-stone-200 sm:px-4">
                <div className="flex items-center gap-2 text-stone-300">
                  <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium">
                    {previewImageIndex + 1} / {previewableImages.length}
                  </span>
                  <span className="hidden text-xs text-stone-400 sm:inline">当前会话成功图片预览</span>
                </div>

                <div className="flex items-center gap-2">
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
