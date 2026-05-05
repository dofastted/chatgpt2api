"use client";

/* eslint-disable @next/next/no-img-element -- This page renders uploaded and generated data URLs; Next Image optimization is not useful here. */
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  CirclePlus,
  Copy,
  Download,
  Images,
  LoaderCircle,
  PanelRightClose,
  PanelRightOpen,
  PanelLeftClose,
  PanelLeftOpen,
  MessageSquarePlus,
  RotateCcw,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
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
  getImageConversationDetail,
  getImageGenerationPreference,
  listImageConversationSummaries,
  saveImageConversation,
  saveImageGenerationPreference,
  type ImageConversation,
  type ImageConversationTurn,
  type StoredInputImage,
  type StoredImage,
} from "@/store/image-conversations";
import { getStoredAuthKey } from "@/store/auth";
import {
  addUserGalleryWaterfallItem,
  buildPromptPreview,
  listUserGalleryPrompts,
  listUserGalleryWaterfallItems,
  loadGalleryPromptStats,
  promptKey,
  recordGalleryPromptUse,
  type GalleryPromptStats,
  type UserGalleryPrompt,
  type UserGalleryWaterfallItem,
} from "@/store/gallery-prompts";
import { cn } from "@/lib/utils";
import {
  calculateImageSizeFromPreference,
  DEFAULT_IMAGE_GENERATION_PREFERENCE,
  formatImagePreferenceLabel,
  formatImageSizeLabel,
  IMAGE_ASPECT_RATIO_PRESETS,
  IMAGE_RESOLUTION_AUTO,
  IMAGE_RESOLUTION_PRESETS,
  normalizeImageGenerationPreference,
  resolveEffectiveImageGenerationPreference,
  type ImageAspectRatioPreset,
  type ImageGenerationPreference,
  type ImageResolutionPreference,
} from "@/lib/image-size";

const imageModelLabels: Record<ImageModel, string> = {
  "gpt-image-2": "基础",
  "gpt-image-2-2K": "2K",
  "gpt-image-2-4K": "4K",
};

const DEFAULT_IMAGE_PRICING: Record<ImageModel, number> = {
  "gpt-image-2": 2,
  "gpt-image-2-2K": 2,
  "gpt-image-2-4K": 8,
};
const MAX_IMAGES_PER_REQUEST = 10;
const PRIMARY_IMAGE_COUNT_OPTIONS = ["1", "2", "4", "10"];
const MAX_INPUT_IMAGE_BYTES = 8 * 1024 * 1024;
const activeGenerationKeys = new Set<string>();
const GALLERY_PROMPT_SUGGESTION_COUNT = 8;
const GALLERY_RAIL_ITEM_COUNT = 48;
const DEFAULT_GALLERY_ASPECT_RATIO = 0.8;
const GALLERY_RAIL_AUTO_SCROLL_PIXELS_PER_SECOND = 48;
const GALLERY_RAIL_COLUMN_WIDTH_ESTIMATE = 128;
const INTERRUPTED_GENERATION_MESSAGE =
  "页面已重新打开，未找回这个请求。请重新发送。";

type GallerySeedItem = {
  id: number | string;
  postNumber: number;
  username: string;
  imageIndex: number;
  title: string;
  imageUrl: string;
  downloadPath: string;
  postUrl: string;
  prompt: string;
  promptPreview: string;
  hasPrompt: boolean;
  useCount?: number;
  randomRank?: number;
  aspectRatio?: number;
  isUserGenerated?: boolean;
};

type GalleryImageDimension = {
  id: number | string;
  width: number;
  height: number;
  aspectRatio: number;
};

function buildUserPromptSuggestion(item: UserGalleryPrompt): GallerySeedItem {
  return {
    id: item.id,
    postNumber: 0,
    username: "我",
    imageIndex: 0,
    title: "我添加的 prompt",
    imageUrl: "",
    downloadPath: "",
    postUrl: "",
    prompt: item.prompt,
    promptPreview: item.promptPreview,
    hasPrompt: true,
    useCount: item.useCount,
  };
}

function buildUserWaterfallSeedItem(item: UserGalleryWaterfallItem): GallerySeedItem {
  return {
    id: item.id,
    postNumber: 0,
    username: "我",
    imageIndex: 0,
    title: "我的作品",
    imageUrl: item.imageUrl,
    downloadPath: "",
    postUrl: "",
    prompt: item.prompt,
    promptPreview: item.promptPreview,
    hasPrompt: Boolean(item.prompt),
    aspectRatio: item.aspectRatio,
    isUserGenerated: true,
  };
}

function buildWaterfallSourceImageId(
  conversationId: string,
  turnId: string,
  imageId: string,
) {
  return `${conversationId}:${turnId}:${imageId}`;
}

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

function formatConversationStatus(conversation: ImageConversation) {
  const turn = getLatestTurn(conversation);
  if (!turn) {
    return "草稿";
  }
  if (turn.status === "queued") {
    return "等待";
  }
  if (turn.status === "assigning_account") {
    return "分配账号";
  }
  if (turn.status === "running") {
    return "生成中";
  }
  if (turn.status === "success") {
    return "完成";
  }
  if (turn.status === "error") {
    return "失败";
  }
  return "草稿";
}

function isPendingTurnStatus(status: ImageConversationTurn["status"]) {
  return (
    status === "queued" ||
    status === "assigning_account" ||
    status === "running"
  );
}

function resolveImageModelFromPreference(
  preference: ImageGenerationPreference,
  prompt?: string | null,
): ImageModel {
  const normalized = resolveEffectiveImageGenerationPreference(
    preference,
    prompt,
  );
  if (normalized.resolution === "2k") {
    return "gpt-image-2-2K";
  }
  if (normalized.resolution === "4k") {
    return "gpt-image-2-4K";
  }
  return "gpt-image-2";
}

function clampImageCount(value: string | number | null | undefined) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(1, Math.min(MAX_IMAGES_PER_REQUEST, parsed));
}

function resolveSizeDraftMode(preference: ImageGenerationPreference): SizeDraftMode {
  const normalized = normalizeImageGenerationPreference(preference);
  if (
    normalized.resolution === IMAGE_RESOLUTION_AUTO &&
    normalized.ratio === "auto"
  ) {
    return "auto";
  }
  if (normalized.resolution === IMAGE_RESOLUTION_AUTO) {
    return "ratio";
  }
  if (normalized.ratio === "auto") {
    return "resolution";
  }
  return "resolution";
}

function normalizeImagePreferenceForMode(
  mode: SizeDraftMode,
  preference: ImageGenerationPreference,
): ImageGenerationPreference {
  const normalized = normalizeImageGenerationPreference(preference);
  if (mode === "auto") {
    return { ...DEFAULT_IMAGE_GENERATION_PREFERENCE };
  }
  if (mode === "resolution") {
    return {
      resolution:
        normalized.resolution === IMAGE_RESOLUTION_AUTO
          ? "1k"
          : normalized.resolution,
      ratio: "auto",
    };
  }
  if (mode === "ratio") {
    return {
      resolution: IMAGE_RESOLUTION_AUTO,
      ratio: normalized.ratio === "auto" ? "1:1" : normalized.ratio,
    };
  }
  return {
    resolution:
      normalized.resolution === IMAGE_RESOLUTION_AUTO
        ? "1k"
        : normalized.resolution,
    ratio: "auto",
  };
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

type SizeDialogState = {
  resolution: ImageResolutionPreference;
  ratio: ImageAspectRatioPreset;
};

type SizeDraftMode = "auto" | "resolution" | "ratio";

type ImageQueueStatusSnapshot = Awaited<
  ReturnType<typeof fetchImageQueueStatus>
>;

type GalleryPreviewItem = GallerySeedItem;

function formatInputImageSize(sizeBytes: number) {
  if (sizeBytes >= 1024 * 1024) {
    return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`;
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

function createClientRequestId(prefix = "") {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    const value = crypto.randomUUID();
    return prefix ? `${prefix}${value}` : value;
  }
  return prefix ? `${prefix}fallback-request-id` : "fallback-request-id";
}

function ImageInspirationRail({
  items,
  imageDimensions,
  isHidden,
  isLoading,
  shouldReduceMotion,
  onHide,
  onOpenPreview,
}: {
  items: GallerySeedItem[];
  imageDimensions: Record<string, GalleryImageDimension>;
  isHidden: boolean;
  isLoading: boolean;
  shouldReduceMotion: boolean;
  onHide: () => void;
  onOpenPreview: (item: GallerySeedItem) => void;
}) {
  const railItems = useMemo(
    () => items.filter((item) => item.imageUrl).slice(0, GALLERY_RAIL_ITEM_COUNT),
    [items],
  );
  const scrollViewportRef = useRef<HTMLDivElement | null>(null);
  const autoScrollTopRef = useRef(0);
  const autoScrollRemainderRef = useRef(0);
  const resumeTimerRef = useRef<number | null>(null);
  const [isAutoScrollPaused, setIsAutoScrollPaused] = useState(false);
  const transition = shouldReduceMotion
    ? { duration: 0 }
    : { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const };
  const railColumns = useMemo(() => {
    const columns: GallerySeedItem[][] = [[], []];
    const columnHeights = [0, 0];
    for (const item of railItems) {
      const aspectRatio =
        item.aspectRatio ||
        imageDimensions[String(item.id)]?.aspectRatio ||
        DEFAULT_GALLERY_ASPECT_RATIO;
      const targetColumn = columnHeights[0] <= columnHeights[1] ? 0 : 1;
      columns[targetColumn].push(item);
      columnHeights[targetColumn] +=
        GALLERY_RAIL_COLUMN_WIDTH_ESTIMATE / Math.max(0.2, aspectRatio) +
        (item.hasPrompt ? 48 : 28);
    }
    return columns;
  }, [imageDimensions, railItems]);

  const pauseAutoScroll = useCallback(() => {
    if (resumeTimerRef.current !== null) {
      window.clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = null;
    }
    setIsAutoScrollPaused(true);
  }, []);

  const scheduleAutoScrollResume = useCallback(() => {
    if (resumeTimerRef.current !== null) {
      window.clearTimeout(resumeTimerRef.current);
    }
    resumeTimerRef.current = window.setTimeout(() => {
      setIsAutoScrollPaused(false);
      resumeTimerRef.current = null;
    }, 3000);
  }, []);

  useEffect(
    () => () => {
      if (resumeTimerRef.current !== null) {
        window.clearTimeout(resumeTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    const element = scrollViewportRef.current;
    if (
      !element ||
      isHidden ||
      isLoading ||
      isAutoScrollPaused ||
      railItems.length === 0
    ) {
      return;
    }
    let frameId = 0;
    let previousTime = performance.now();
    const tick = (time: number) => {
      const viewport = scrollViewportRef.current;
      if (!viewport) {
        frameId = window.requestAnimationFrame(tick);
        return;
      }
      const elapsed = Math.max(0, time - previousTime);
      previousTime = time;
      const maxScroll = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
      if (maxScroll > 0) {
        if (viewport.scrollTop >= maxScroll - 4) {
          autoScrollTopRef.current = 0;
          autoScrollRemainderRef.current = 0;
          viewport.scrollTop = 0;
        } else {
          if (Math.abs(viewport.scrollTop - autoScrollTopRef.current) > 2) {
            autoScrollTopRef.current = viewport.scrollTop;
            autoScrollRemainderRef.current = 0;
          }
          autoScrollRemainderRef.current +=
            (GALLERY_RAIL_AUTO_SCROLL_PIXELS_PER_SECOND * elapsed) / 1000;
          const wholePixels = Math.floor(autoScrollRemainderRef.current);
          if (wholePixels > 0) {
            autoScrollRemainderRef.current -= wholePixels;
            autoScrollTopRef.current = Math.min(maxScroll, viewport.scrollTop + wholePixels);
            viewport.scrollTop = autoScrollTopRef.current;
          }
        }
      }
      frameId = window.requestAnimationFrame(tick);
    };
    frameId = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frameId);
  }, [isAutoScrollPaused, isHidden, isLoading, railItems.length]);

  return (
    <motion.aside
      className="image-chat-gallery-rail hidden h-full min-w-0 shrink-0 overflow-hidden border-l border-border bg-background lg:flex"
      initial={false}
      animate={{
        width: isHidden ? 0 : 286,
        opacity: isHidden ? 0 : 1,
        x: isHidden ? 16 : 0,
      }}
      transition={transition}
      aria-hidden={isHidden}
    >
      <div className="flex h-full w-[286px] shrink-0 flex-col">
        <div className="flex min-h-14 items-center justify-between gap-2 border-b border-border px-3 py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              画廊灵感
            </div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              点图预览
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-9 shrink-0"
            onClick={onHide}
            aria-label="隐藏画廊"
            title="隐藏画廊"
          >
            <PanelRightClose className="size-4" />
          </Button>
        </div>

        <div
          ref={scrollViewportRef}
          className="hide-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-2.5 py-3"
          data-auto-scroll="image-inspiration-rail"
          onMouseEnter={pauseAutoScroll}
          onMouseLeave={scheduleAutoScrollResume}
          style={{ touchAction: "pan-y" }}
        >
          {isLoading ? (
            <div className="flex min-h-[200px] items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              正在加载
            </div>
          ) : railItems.length === 0 ? (
            <div className="flex min-h-[200px] items-center justify-center text-sm text-muted-foreground">
              暂无图片
            </div>
          ) : (
            <div className="grid grid-cols-2 items-start gap-2">
              {railColumns.map((column, columnIndex) => (
                <div key={columnIndex} className="flex min-w-0 flex-col gap-2">
                  {column.map((item) => {
                    const aspectRatio =
                      item.aspectRatio ||
                      imageDimensions[String(item.id)]?.aspectRatio ||
                      DEFAULT_GALLERY_ASPECT_RATIO;
                    const itemLabel = item.isUserGenerated
                      ? "我的作品"
                      : `#${item.postNumber} / 图 ${item.imageIndex}`;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => onOpenPreview(item)}
                        className="group block w-full overflow-hidden rounded-lg border border-border bg-muted text-left transition hover:border-primary/60 focus-visible:ring-4 focus-visible:ring-ring/20 focus-visible:outline-none"
                        aria-label={`预览${itemLabel}`}
                      >
                        <div
                          className="relative w-full overflow-hidden"
                          style={{ aspectRatio: String(aspectRatio) }}
                        >
                          <img
                            src={item.imageUrl}
                            alt={item.title}
                            loading="lazy"
                            className="absolute inset-0 h-full w-full object-cover transition duration-300 group-hover:scale-[1.02]"
                          />
                        </div>
                        <div className="px-2 py-1.5">
                          <div className="truncate text-[11px] font-medium text-foreground">
                            {itemLabel}
                          </div>
                          {item.hasPrompt ? (
                            <div className="mt-0.5 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                              {item.promptPreview || item.prompt}
                            </div>
                          ) : null}
                        </div>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </motion.aside>
  );
}

function getConversationTurns(
  conversation: ImageConversation | null | undefined,
) {
  return Array.isArray(conversation?.turns) ? conversation.turns : [];
}

function getLatestTurn(conversation: ImageConversation | null | undefined) {
  const turns = getConversationTurns(conversation);
  return turns[turns.length - 1] || null;
}

function getPreviousResponseIdForTurn(
  conversation: ImageConversation | null | undefined,
  turnId?: string,
) {
  const turns = getConversationTurns(conversation);
  const endIndex = turnId
    ? turns.findIndex((turn) => turn.id === turnId)
    : turns.length;
  const candidates = turns.slice(0, endIndex >= 0 ? endIndex : turns.length);
  return (
    [...candidates]
      .reverse()
      .map((turn) => String(turn.responseId || "").trim())
      .find(Boolean) || undefined
  );
}

function updateConversationTurn(
  conversation: ImageConversation,
  turnId: string,
  updater: (turn: ImageConversationTurn) => ImageConversationTurn,
) {
  return {
    ...conversation,
    turns: getConversationTurns(conversation).map((turn) =>
      turn.id === turnId ? updater(turn) : turn,
    ),
  };
}

function buildGenerationKey(
  scope: string,
  conversationId: string,
  turnId: string,
) {
  return `${scope}:${conversationId}:${turnId}`;
}

function isTurnActiveInCurrentSession(
  scope: string,
  conversation: ImageConversation,
  turn: ImageConversationTurn,
) {
  return activeGenerationKeys.has(
    buildGenerationKey(scope, conversation.id, turn.id),
  );
}

function turnNeedsInterruptedReset(
  scope: string | null,
  conversation: ImageConversation,
  turn: ImageConversationTurn,
) {
  if (!scope || isTurnActiveInCurrentSession(scope, conversation, turn)) {
    return false;
  }
  return (
    isPendingTurnStatus(turn.status) ||
    (turn.images || []).some((image) => image.status === "loading")
  );
}

function resetInterruptedTurn(
  turn: ImageConversationTurn,
  finishedAt: string,
): ImageConversationTurn {
  return {
    ...turn,
    status: "error",
    error: turn.error || INTERRUPTED_GENERATION_MESSAGE,
    lastError: turn.lastError || INTERRUPTED_GENERATION_MESSAGE,
    requestFinishedAt: turn.requestFinishedAt || finishedAt,
    images: (turn.images || []).map((image) =>
      image.status === "loading"
        ? {
            ...image,
            status: "error" as const,
            error: image.error || INTERRUPTED_GENERATION_MESSAGE,
          }
        : image,
    ),
  };
}

function resetInterruptedConversation(
  conversation: ImageConversation,
  scope: string | null,
  finishedAt = new Date().toISOString(),
) {
  let resetCount = 0;
  const turns = getConversationTurns(conversation).map((turn) => {
    if (!turnNeedsInterruptedReset(scope, conversation, turn)) {
      return turn;
    }
    resetCount += 1;
    return resetInterruptedTurn(turn, finishedAt);
  });

  if (resetCount === 0) {
    return { conversation, resetCount };
  }

  const latestTurn = turns[turns.length - 1];
  return {
    conversation: {
      ...conversation,
      turns,
      prompt: latestTurn?.prompt,
      model: latestTurn?.model,
      count: latestTurn?.count,
      size: latestTurn?.size,
      copiedText: latestTurn?.copiedText,
      inputImage: latestTurn?.inputImage,
      images: latestTurn?.images,
      status: latestTurn?.status,
      error: latestTurn?.error,
      queueRequestId: latestTurn?.queueRequestId,
      requestStartedAt: latestTurn?.requestStartedAt,
      requestFinishedAt: latestTurn?.requestFinishedAt,
      lastError: latestTurn?.lastError,
      responseId: latestTurn?.responseId,
    },
    resetCount,
  };
}

function buildQueueFailureMessage(item: ImageQueueItem) {
  const error = String(item.error || "").trim();
  if (error) {
    return error;
  }
  return item.status === "rejected"
    ? "图片请求被拒绝，请重新发送。"
    : "图片生成失败，请重新发送。";
}

function failTurnFromQueueStatus(
  turn: ImageConversationTurn,
  item: ImageQueueItem,
  finishedAt = new Date().toISOString(),
): ImageConversationTurn {
  const message = buildQueueFailureMessage(item);
  return {
    ...turn,
    status: "error",
    error: message,
    lastError: message,
    requestFinishedAt: turn.requestFinishedAt || finishedAt,
    images: (turn.images || []).map((image) =>
      image.status === "loading"
        ? {
            ...image,
            status: "error" as const,
            error: image.error || message,
          }
        : image,
    ),
  };
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

export default function ImagePage() {
  const didLoadQuotaRef = useRef(false);
  const conversationsRef = useRef<ImageConversation[]>([]);
  const shouldReduceMotion = useReducedMotion();
  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageSize, setImageSize] = useState("auto");
  const [imagePreference, setImagePreference] =
    useState<ImageGenerationPreference>(DEFAULT_IMAGE_GENERATION_PREFERENCE);
  const [isSizeDialogOpen, setIsSizeDialogOpen] = useState(false);
  const [isClearHistoryDialogOpen, setIsClearHistoryDialogOpen] =
    useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(true);
  const [isDesktopViewport, setIsDesktopViewport] = useState(false);
  const [isInspirationRailHidden, setIsInspirationRailHidden] =
    useState(false);
  const [sizeDraftMode, setSizeDraftMode] = useState<SizeDraftMode>("auto");
  const [sizeDraft, setSizeDraft] = useState<SizeDialogState>({
    ...DEFAULT_IMAGE_GENERATION_PREFERENCE,
  });
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<
    string | null
  >(null);
  const [previewImageId, setPreviewImageId] = useState<string | null>(null);
  const [galleryPreviewItem, setGalleryPreviewItem] =
    useState<GalleryPreviewItem | null>(null);
  const [galleryItems, setGalleryItems] = useState<GallerySeedItem[]>([]);
  const [galleryImageDimensions, setGalleryImageDimensions] = useState<
    Record<string, GalleryImageDimension>
  >({});
  const [userGalleryPrompts, setUserGalleryPrompts] = useState<UserGalleryPrompt[]>([]);
  const [userGalleryWaterfallItems, setUserGalleryWaterfallItems] = useState<
    UserGalleryWaterfallItem[]
  >([]);
  const [galleryPromptStats, setGalleryPromptStats] = useState<GalleryPromptStats>({});
  const [galleryRandomRanks, setGalleryRandomRanks] = useState<Record<string, number>>({});
  const [isGalleryDataLoading, setIsGalleryDataLoading] = useState(true);
  const [conversationScope, setConversationScope] = useState<string | null>(
    null,
  );
  const [hasLoadedHistory, setHasLoadedHistory] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [loadingConversationDetailId, setLoadingConversationDetailId] =
    useState<string | null>(null);
  const [isUploadingInputImage, setIsUploadingInputImage] = useState(false);
  const [inputImage, setInputImage] = useState<PendingInputImage | null>(null);
  const [availableQuota, setAvailableQuota] = useState<number | null>(null);
  const [currentPricing, setCurrentPricing] = useState<Record<
    ImageModel,
    number
  > | null>(null);
  const [queueStatus, setQueueStatus] =
    useState<ImageQueueStatusSnapshot | null>(null);
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputImageRef = useRef<HTMLInputElement>(null);

  const focusPromptInput = useCallback(() => {
    window.setTimeout(() => {
      textareaRef.current?.focus();
      textareaRef.current?.scrollIntoView({
        block: "nearest",
        behavior: shouldReduceMotion ? "auto" : "smooth",
      });
    }, 0);
  }, [shouldReduceMotion]);

  const applyPromptToComposer = useCallback(
    (prompt: string) => {
      const normalizedPrompt = String(prompt || "").trim();
      if (!normalizedPrompt) {
        toast.error("这张图没有 prompt");
        return;
      }
      if (conversationScope) {
        void recordGalleryPromptUse(conversationScope, normalizedPrompt).then(async () => {
          const [nextPrompts, nextStats] = await Promise.all([
            listUserGalleryPrompts(conversationScope),
            loadGalleryPromptStats(conversationScope),
          ]);
          setUserGalleryPrompts(nextPrompts);
          setGalleryPromptStats(nextStats);
        });
      }
      setImagePrompt(normalizedPrompt);
      focusPromptInput();
    },
    [conversationScope, focusPromptInput],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const prompt = params.get("prompt");
    if (!prompt) {
      return;
    }
    const timer = window.setTimeout(() => {
      setImagePrompt(prompt);
      if (params.get("focus") === "prompt") {
        focusPromptInput();
      } else {
        textareaRef.current?.focus();
      }
      params.delete("prompt");
      params.delete("focus");
      const nextQuery = params.toString();
      const nextUrl = nextQuery ? `/image?${nextQuery}` : "/image";
      window.history.replaceState({}, "", nextUrl);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [focusPromptInput]);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 1024px)");
    const syncViewport = () => {
      setIsDesktopViewport(mediaQuery.matches);
    };
    syncViewport();
    mediaQuery.addEventListener("change", syncViewport);
    return () => {
      mediaQuery.removeEventListener("change", syncViewport);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadGalleryData = async () => {
      setIsGalleryDataLoading(true);
      try {
        const [itemsMod, dimensionsMod] = await Promise.all([
          import("@/data/gallery-ui-seed.json"),
          import("@/data/gallery-image-dimensions.json").catch(() => ({
            default: [],
          })),
        ]);
        if (cancelled) {
          return;
        }
        const nextItems = (itemsMod.default || []) as GallerySeedItem[];
        const nextDimensions = Object.fromEntries(
          ((dimensionsMod.default || []) as GalleryImageDimension[]).map(
            (item) => [String(item.id), item],
          ),
        );
        setGalleryItems(nextItems);
        setGalleryImageDimensions(nextDimensions);
        setGalleryRandomRanks(
          Object.fromEntries(nextItems.map((item) => [String(item.id), Math.random()])),
        );
      } finally {
        if (!cancelled) {
          setIsGalleryDataLoading(false);
        }
      }
    };
    void loadGalleryData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!conversationScope) {
      return;
    }
    let cancelled = false;
    const loadGalleryPromptData = async () => {
      try {
        const [nextPrompts, nextStats, nextWaterfallItems] = await Promise.all([
          listUserGalleryPrompts(conversationScope),
          loadGalleryPromptStats(conversationScope),
          listUserGalleryWaterfallItems(conversationScope),
        ]);
        if (!cancelled) {
          setUserGalleryPrompts(nextPrompts);
          setGalleryPromptStats(nextStats);
          setUserGalleryWaterfallItems(nextWaterfallItems);
        }
      } catch {
        if (!cancelled) {
          setUserGalleryPrompts([]);
          setGalleryPromptStats({});
          setUserGalleryWaterfallItems([]);
        }
      }
    };
    void loadGalleryPromptData();
    return () => {
      cancelled = true;
    };
  }, [conversationScope]);

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
    () => clampImageCount(imageCount),
    [imageCount],
  );
  const effectivePricing = useMemo(
    () => currentPricing || DEFAULT_IMAGE_PRICING,
    [currentPricing],
  );
  const imageModel = useMemo(
    () => resolveImageModelFromPreference(imagePreference, imagePrompt),
    [imagePreference, imagePrompt],
  );
  const effectiveImagePreference = useMemo(
    () =>
      resolveEffectiveImageGenerationPreference(imagePreference, imagePrompt),
    [imagePreference, imagePrompt],
  );
  const normalizedSizeDraft = useMemo(
    () => normalizeImagePreferenceForMode(sizeDraftMode, sizeDraft),
    [sizeDraftMode, sizeDraft],
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
  const selectedConversation = useMemo(
    () =>
      conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const selectedTurn = useMemo(
    () => getLatestTurn(selectedConversation),
    [selectedConversation],
  );
  const activeRequestIds = useMemo(
    () =>
      Array.from(
        new Set(
          conversations
            .flatMap((conversation) =>
              getConversationTurns(conversation).map((turn) => ({
                conversation,
                turn,
              })),
            )
            .filter(
              ({ conversation, turn }) =>
                conversationScope !== null &&
                isTurnActiveInCurrentSession(
                  conversationScope,
                  conversation,
                  turn,
                ) &&
                Boolean(turn.queueRequestId) &&
                isPendingTurnStatus(turn.status),
            )
            .map(({ turn }) => String(turn.queueRequestId || "").trim())
            .filter(Boolean),
        ),
      ),
    [conversationScope, conversations],
  );
  const interruptedRequestCount = useMemo(
    () =>
      conversations.reduce(
        (count, conversation) =>
          count +
          getConversationTurns(conversation).filter((turn) =>
            turnNeedsInterruptedReset(conversationScope, conversation, turn),
          ).length,
        0,
      ),
    [conversationScope, conversations],
  );
  const selectedConversationRequestId = selectedTurn?.queueRequestId || null;
  const isComposerGenerating = activeRequestIds.length > 0;
  const previewableImages = useMemo<PreviewableImage[]>(
    () =>
      (selectedTurn?.images || []).flatMap((image, index) =>
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
    [selectedTurn],
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
  const emptyPromptSuggestions = useMemo(
    () => {
      const userItems = userGalleryPrompts.map(buildUserPromptSuggestion);
      const seedItems = galleryItems
        .filter((item) => item.hasPrompt && String(item.prompt || "").trim())
        .map((item) => ({
          ...item,
          useCount: Math.max(0, Number(galleryPromptStats[promptKey(item.prompt)] || 0)),
          randomRank: galleryRandomRanks[String(item.id)] ?? 0,
        }))
        .sort((a, b) => {
          const usageDiff = Math.max(0, Number(b.useCount || 0)) - Math.max(0, Number(a.useCount || 0));
          if (usageDiff !== 0) {
            return usageDiff;
          }
          return Number(a.randomRank || 0) - Number(b.randomRank || 0);
        });
      return [...userItems, ...seedItems].slice(0, GALLERY_PROMPT_SUGGESTION_COUNT);
    },
    [galleryItems, galleryPromptStats, galleryRandomRanks, userGalleryPrompts],
  );
  const rankedGalleryItems = useMemo(
    () => {
      const userItems = userGalleryWaterfallItems.map(buildUserWaterfallSeedItem);
      const seedItems = galleryItems
        .map((item) => ({
          ...item,
          useCount: item.hasPrompt ? Math.max(0, Number(galleryPromptStats[promptKey(item.prompt)] || 0)) : 0,
          randomRank: galleryRandomRanks[String(item.id)] ?? 0,
        }))
        .sort((a, b) => {
          const usageDiff = Math.max(0, Number(b.useCount || 0)) - Math.max(0, Number(a.useCount || 0));
          if (usageDiff !== 0) {
            return usageDiff;
          }
          return Number(a.randomRank || 0) - Number(b.randomRank || 0);
        });
      return [...userItems, ...seedItems];
    },
    [
      galleryItems,
      galleryPromptStats,
      galleryRandomRanks,
      userGalleryWaterfallItems,
    ],
  );
  const userWaterfallSourceImageIds = useMemo(
    () =>
      new Set(
        userGalleryWaterfallItems
          .map((item) => String(item.sourceImageId || "").trim())
          .filter(Boolean),
      ),
    [userGalleryWaterfallItems],
  );
  const currentQueueRequest = useMemo(() => {
    if (!selectedTurn?.queueRequestId) {
      return null;
    }
    return (
      (queueStatus?.items || []).find(
        (item) => item.request_id === selectedTurn.queueRequestId,
      ) ||
      (queueStatus?.request?.request_id === selectedTurn.queueRequestId
        ? queueStatus.request
        : null)
    );
  }, [queueStatus, selectedTurn]);
  const currentQueueProgressText = useMemo(
    () => formatQueueProgressText(currentQueueRequest),
    [currentQueueRequest],
  );
  const composerStatusText = isQuotaInsufficient
    ? `至少需要 ${requestCost} 额度`
    : isUploadingInputImage
      ? "图片上传中"
      : interruptedRequestCount > 0
        ? `${interruptedRequestCount} 个旧请求需要重置`
        : inputImage
          ? `已附加参考图，${formatImagePreferenceLabel(effectiveImagePreference)}`
          : `${formatImagePreferenceLabel(effectiveImagePreference)}，Enter 发送`;
  const sidebarTransition = shouldReduceMotion
    ? { duration: 0 }
    : { duration: 0.5, ease: [0.22, 1, 0.36, 1] as const };
  const listTransition = shouldReduceMotion
    ? { duration: 0 }
    : { duration: 0.22, ease: [0.22, 1, 0.36, 1] as const };
  const isSidebarVisible = isDesktopViewport
    ? !isSidebarCollapsed
    : isSidebarOpen;

  useEffect(() => {
    let cancelled = false;

    const loadScope = async () => {
      try {
        const authKey = await getStoredAuthKey();
        if (!cancelled) {
          const nextScope = String(authKey || "").trim() || "__anonymous__";
          conversationsRef.current = [];
          setConversations([]);
          setSelectedConversationId(null);
          setPreviewImageId(null);
          setHasLoadedHistory(false);
          setIsLoadingHistory(false);
          setConversationScope(nextScope);
        }
      } catch (error) {
        if (!cancelled) {
          conversationsRef.current = [];
          setConversations([]);
          setSelectedConversationId(null);
          setPreviewImageId(null);
          setHasLoadedHistory(false);
          setIsLoadingHistory(false);
          setConversationScope("__anonymous__");
        }
      }
    };

    void loadScope();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadConversationHistory = useCallback(async () => {
    if (conversationScope === null) {
      return;
    }

    setIsLoadingHistory(true);
    setPreviewImageId(null);
    try {
      const items = await listImageConversationSummaries(conversationScope);
      const now = new Date().toISOString();
      const normalizedItems = items.map(
        (item) =>
          resetInterruptedConversation(item, conversationScope, now)
            .conversation,
      );
      conversationsRef.current = normalizedItems;
      setConversations(normalizedItems);
      setHasLoadedHistory(true);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "读取会话记录失败";
      toast.error(message);
    } finally {
      setIsLoadingHistory(false);
    }
  }, [conversationScope]);

  useEffect(() => {
    if (conversationScope === null || hasLoadedHistory || isLoadingHistory) {
      return;
    }
    if (!isSidebarOpen && isSidebarCollapsed) {
      return;
    }

    let cancelled = false;

    const load = async () => {
      await loadConversationHistory();
    };

    if (!cancelled) {
      void load();
    }
    return () => {
      cancelled = true;
    };
  }, [
    conversationScope,
    hasLoadedHistory,
    isLoadingHistory,
    isSidebarCollapsed,
    isSidebarOpen,
    loadConversationHistory,
  ]);

  useEffect(() => {
    if (conversationScope === null) {
      return;
    }

    let cancelled = false;

    const loadPreference = async () => {
      try {
        const preference =
          await getImageGenerationPreference(conversationScope);
        if (cancelled) {
          return;
        }
        const normalized = normalizeImageGenerationPreference(preference);
        setImagePreference(normalized);
        setSizeDraft(normalized);
        setSizeDraftMode(resolveSizeDraftMode(normalized));
        setImageSize(calculateImageSizeFromPreference(normalized));
      } catch {
        if (!cancelled) {
          const fallback = DEFAULT_IMAGE_GENERATION_PREFERENCE;
          setImagePreference(fallback);
          setSizeDraft(fallback);
          setSizeDraftMode(resolveSizeDraftMode(fallback));
          setImageSize(calculateImageSizeFromPreference(fallback));
        }
      }
    };

    void loadPreference();
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
          "gpt-image-2": Math.max(
            0,
            Number(
              data.pricing["gpt-image-2"] ??
                DEFAULT_IMAGE_PRICING["gpt-image-2"],
            ),
          ),
          "gpt-image-2-2K": Math.max(
            0,
            Number(
              data.pricing["gpt-image-2-2K"] ??
                DEFAULT_IMAGE_PRICING["gpt-image-2-2K"],
            ),
          ),
          "gpt-image-2-4K": Math.max(
            0,
            Number(
              data.pricing["gpt-image-2-4K"] ??
                DEFAULT_IMAGE_PRICING["gpt-image-2-4K"],
            ),
          ),
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
        const requestIds =
          activeRequestIds.length > 0 ? activeRequestIds : [null];
        const snapshots = await Promise.all(
          requestIds.map((requestId) =>
            fetchImageQueueStatus(requestId).catch(() => null),
          ),
        );
        if (!cancelled) {
          const mergedItems = snapshots.flatMap((snapshot) => [
            ...(snapshot?.items || []),
            ...(snapshot?.request ? [snapshot.request] : []),
          ]);
          const uniqueItems = Array.from(
            new Map(
              mergedItems.map((item) => [item.request_id, item]),
            ).values(),
          );
          const baseSnapshot = snapshots.find((snapshot) => snapshot) || null;
          const terminalItems = uniqueItems.filter(
            (item) => item.status === "failed" || item.status === "rejected",
          );
          setQueueStatus(
            baseSnapshot
              ? {
                  ...baseSnapshot,
                  request:
                    uniqueItems.find(
                      (item) =>
                        item.request_id === selectedConversationRequestId,
                    ) ||
                    baseSnapshot.request ||
                    null,
                  items: uniqueItems,
                }
              : null,
          );
          if (terminalItems.length > 0 && conversationScope) {
            const terminalItemsByRequestId = new Map(
              terminalItems.map((item) => [item.request_id, item]),
            );
            const finishedAt = new Date().toISOString();
            const nextConversations = conversationsRef.current.map(
              (conversation) => {
                let changed = false;
                const turns = getConversationTurns(conversation).map((turn) => {
                  const requestId = String(turn.queueRequestId || "").trim();
                  const terminalItem = terminalItemsByRequestId.get(requestId);
                  if (!terminalItem || !isPendingTurnStatus(turn.status)) {
                    return turn;
                  }
                  changed = true;
                  return failTurnFromQueueStatus(turn, terminalItem, finishedAt);
                });
                if (!changed) {
                  return conversation;
                }
                const latestTurn = turns[turns.length - 1];
                return {
                  ...conversation,
                  turns,
                  status: latestTurn?.status,
                  error: latestTurn?.error,
                  lastError: latestTurn?.lastError,
                  requestFinishedAt: latestTurn?.requestFinishedAt,
                  images: latestTurn?.images,
                };
              },
            );
            const changedConversations = nextConversations.filter(
              (conversation, index) =>
                conversation !== conversationsRef.current[index],
            );
            if (changedConversations.length > 0) {
              conversationsRef.current = nextConversations;
              setConversations(nextConversations);
              await Promise.all(
                changedConversations.map((conversation) =>
                  saveImageConversation(conversationScope, conversation),
                ),
              );
            }
          }
        }
      } catch {
        if (!cancelled) {
          setQueueStatus(null);
        }
      }
    };

    void syncQueueStatus();
    const intervalMs = activeRequestIds.length > 0 ? 1500 : 10000;
    const intervalId = window.setInterval(() => {
      void syncQueueStatus();
    }, intervalMs);
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
    setSelectedConversationId(null);
    setPreviewImageId(null);
    setImagePrompt("");
    setInputImage(null);
    setIsSidebarOpen(false);
    focusPromptInput();
  };

  const handleSelectConversation = async (conversation: ImageConversation) => {
    setSelectedConversationId(conversation.id);
    setPreviewImageId(null);
    setIsSidebarOpen(false);
    if (!conversationScope || !conversation.isSummary) {
      return;
    }

    try {
      setLoadingConversationDetailId(conversation.id);
      const detail = await getImageConversationDetail(
        conversationScope,
        conversation.id,
      );
      const { conversation: nextDetail, resetCount } =
        resetInterruptedConversation(detail, conversationScope);
      conversationsRef.current = [
        nextDetail,
        ...conversationsRef.current.filter((item) => item.id !== nextDetail.id),
      ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      setConversations(conversationsRef.current);
      if (resetCount > 0) {
        await saveImageConversation(conversationScope, nextDetail);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "读取会话详情失败";
      toast.error(message);
    } finally {
      setLoadingConversationDetailId((current) =>
        current === conversation.id ? null : current,
      );
    }
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
        ? await listImageConversationSummaries(conversationScope)
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
      setIsClearHistoryDialogOpen(false);
      toast.success("已清空历史记录");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "清空历史记录失败";
      toast.error(message);
    }
  };

  const handleOpenImagePreferenceDialog = () => {
    setSizeDraft(imagePreference);
    setSizeDraftMode(resolveSizeDraftMode(imagePreference));
    setIsSizeDialogOpen(true);
  };

  const handleApplyImageSize = async () => {
    try {
      const nextPreference = normalizeImagePreferenceForMode(sizeDraftMode, sizeDraft);
      const nextSize = calculateImageSizeFromPreference(nextPreference);
      if (conversationScope) {
        await saveImageGenerationPreference(conversationScope, nextPreference);
      }
      setImagePreference(nextPreference);
      setSizeDraft(nextPreference);
      setSizeDraftMode(resolveSizeDraftMode(nextPreference));
      setImageSize(nextSize);
      setIsSizeDialogOpen(false);
      toast.success("画面配置已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "画面配置无效");
    }
  };

  const handleResetInterruptedRequests = async () => {
    if (!conversationScope) {
      toast.error("当前登录信息还在初始化，请稍后再试");
      return;
    }

    const now = new Date().toISOString();
    let resetCount = 0;
    const nextConversations = conversationsRef.current.map((conversation) => {
      const result = resetInterruptedConversation(
        conversation,
        conversationScope,
        now,
      );
      resetCount += result.resetCount;
      return result.conversation;
    });

    if (resetCount === 0) {
      toast.message("没有需要重置的请求");
      return;
    }

    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    setQueueStatus(null);

    const changedFullConversations = nextConversations.filter(
      (conversation) =>
        !conversation.isSummary &&
        getConversationTurns(conversation).some(
          (turn) =>
            turn.lastError === INTERRUPTED_GENERATION_MESSAGE ||
            turn.error === INTERRUPTED_GENERATION_MESSAGE ||
            (turn.images || []).some(
              (image) => image.error === INTERRUPTED_GENERATION_MESSAGE,
            ),
        ),
    );

    await Promise.all(
      changedFullConversations.map((conversation) =>
        saveImageConversation(conversationScope, conversation),
      ),
    );
    toast.success(`已重置 ${resetCount} 个旧请求`);
  };

  const handleGenerateImage = async (retry?: {
    conversation: ImageConversation;
    turn: ImageConversationTurn;
  }) => {
    if (!conversationScope) {
      toast.error("当前登录信息还在初始化，请稍后再试");
      return;
    }
    const prompt = String(retry?.turn.prompt || imagePrompt).trim();
    const currentInputImage = retry?.turn.inputImage || inputImage;
    const targetPreference = normalizeImageGenerationPreference(imagePreference);
    const targetModel =
      retry?.turn.model || resolveImageModelFromPreference(targetPreference, prompt);
    const targetCount = Math.max(
      1,
      Math.min(
        MAX_IMAGES_PER_REQUEST,
        clampImageCount(retry?.turn.count || parsedCount),
      ),
    );
    const targetSize =
      String(retry?.turn.size || calculateImageSizeFromPreference(targetPreference) || imageSize || "auto").trim() ||
      "auto";
    const targetUnitCost = Math.max(
      0,
      Number(effectivePricing[targetModel] || 0),
    );
    const targetRequestCost = targetCount * targetUnitCost;
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }
    if (
      availableQuota !== null &&
      targetRequestCost > Math.max(0, availableQuota)
    ) {
      toast.error(`当前额度不足，本次需要 ${targetRequestCost} 额度`);
      return;
    }

    const now = new Date().toISOString();
    const existingConversation = retry?.conversation || selectedConversation;
    const previousResponseId = retry
      ? getPreviousResponseIdForTurn(existingConversation, retry.turn.id)
      : getLatestTurn(existingConversation)?.responseId;
    const conversationId =
      existingConversation?.clientConversationId ||
      currentInputImage?.clientConversationId ||
      createClientRequestId("conv-");
    const conversationRecordId = existingConversation?.id || conversationId;
    const turnId = createClientRequestId("turn-");
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
    const draftTurn: ImageConversationTurn = {
      id: turnId,
      prompt,
      model: targetModel,
      count: targetCount,
      size: targetSize,
      copiedText: undefined,
      inputImage: draftInputImage,
      images: Array.from({ length: targetCount }, (_, index) => ({
        id: `${turnId}-${index}`,
        status: "loading" as const,
      })),
      createdAt: now,
      status: "queued",
      queueRequestId,
      requestStartedAt: now,
    };
    const draftConversation: ImageConversation = existingConversation
      ? {
          ...existingConversation,
          turns: [...getConversationTurns(existingConversation), draftTurn],
        }
      : {
          id: conversationRecordId,
          clientConversationId: conversationId,
          title: buildConversationTitle(prompt),
          createdAt: now,
          turns: [draftTurn],
        };
    const activeGenerationKey = buildGenerationKey(
      conversationScope,
      conversationRecordId,
      turnId,
    );
    void recordGalleryPromptUse(conversationScope, prompt).then(async () => {
      const [nextPrompts, nextStats] = await Promise.all([
        listUserGalleryPrompts(conversationScope),
        loadGalleryPromptStats(conversationScope),
      ]);
      setUserGalleryPrompts(nextPrompts);
      setGalleryPromptStats(nextStats);
    });

    setSelectedConversationId(conversationRecordId);
    if (!retry) {
      setImagePrompt("");
      setInputImage(null);
    }

    try {
      activeGenerationKeys.add(activeGenerationKey);
      await persistConversation(draftConversation);

      const data = await generateImage(prompt, targetModel, targetCount, {
        inputImageUrl: currentInputImage?.dataUrl,
        inputImageFileId: currentInputImage?.fileId,
        queueRequestId,
        clientConversationId: conversationId,
        previousResponseId,
        size: targetSize,
      });
      const returnedItems = Array.isArray(data.data) ? data.data : [];
      if (data.billing) {
        setAvailableQuota(
          Math.max(0, Number(data.billing.remaining_quota || 0)),
        );
      }
      const nextImages: StoredImage[] = Array.from(
        { length: targetCount },
        (_, index) => {
          const current =
            returnedItems.find((item) => item.index === index) ??
            returnedItems.find(
              (item) =>
                item.index === undefined &&
                returnedItems.indexOf(item) === index,
            );
          if (current?.b64_json) {
            return {
              id: `${turnId}-${index}`,
              status: "success",
              b64_json: current.b64_json,
              mimeType:
                String(current.mime_type || "").trim() ||
                detectImageMimeType(current.b64_json),
            };
          }
          const partialError = Array.isArray(data.partial_errors)
            ? data.partial_errors.find((item) => item.index === index)
            : undefined;
          return {
            id: `${turnId}-${index}`,
            status: "error",
            error:
              String(partialError?.error || "").trim() ||
              `第 ${index + 1} 张没有返回图片数据`,
          };
        },
      );

      const successCount = nextImages.filter(
        (item) => item.status === "success",
      ).length;
      const failedCount = nextImages.length - successCount;
      const returnedText = String(
        data.text_content || data.copied_text || "",
      ).trim();

      if (successCount === 0 && !returnedText) {
        throw new Error("生成图片失败");
      }

      await updateConversation(conversationRecordId, (current) =>
        updateConversationTurn(
          current ?? draftConversation,
          turnId,
          (turn) => ({
            ...turn,
            copiedText: returnedText || undefined,
            images: nextImages,
            status: failedCount > 0 && !returnedText ? "error" : "success",
            error:
              failedCount > 0 && !returnedText
                ? `其中 ${failedCount} 张生成失败`
                : undefined,
            lastError:
              failedCount > 0 && !returnedText
                ? `其中 ${failedCount} 张生成失败`
                : undefined,
            requestFinishedAt: new Date().toISOString(),
            responseId: String(data.id || "").trim() || turn.responseId,
          }),
        ),
      );
      await loadQuota();

      if (successCount === 0 && returnedText) {
        toast.info("未返回图片，已显示上游文本");
      } else if (failedCount > 0) {
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
        turns: getConversationTurns(draftConversation).map((turn) =>
          turn.id === turnId
            ? {
                ...turn,
                status: "error",
                error: message,
                lastError: message,
                requestFinishedAt: new Date().toISOString(),
              }
            : turn,
        ),
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
      const uploadConversationId =
        selectedConversation?.clientConversationId ||
        inputImage?.clientConversationId ||
        createClientRequestId("conv-");
      const [dataUrl, uploadedImage] = await Promise.all([
        readFileAsDataUrl(file),
        uploadInputImage(file, uploadConversationId),
      ]);
      const clientConversationId =
        String(uploadedImage.client_conversation_id || "").trim() ||
        uploadConversationId;
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

  const handleAddImageToWaterfall = async (
    conversation: ImageConversation,
    turn: ImageConversationTurn,
    image: StoredImage,
  ) => {
    if (!conversationScope) {
      toast.error("当前登录信息还在初始化，请稍后再试");
      return;
    }
    if (image.status !== "success" || !image.b64_json) {
      toast.error("图片还没有生成成功");
      return;
    }
    const prompt = String(turn.prompt || "").trim();
    const mimeType =
      String(image.mimeType || "").trim() || detectImageMimeType(image.b64_json);
    try {
      await addUserGalleryWaterfallItem(conversationScope, {
        prompt,
        promptPreview: buildPromptPreview(prompt),
        imageUrl: buildImageDataUrl(image.b64_json, mimeType),
        mimeType,
        sourceConversationId: conversation.id,
        sourceTurnId: turn.id,
        sourceImageId: buildWaterfallSourceImageId(
          conversation.id,
          turn.id,
          image.id,
        ),
      });
      const nextItems =
        await listUserGalleryWaterfallItems(conversationScope);
      setUserGalleryWaterfallItems(nextItems);
      toast.success("已添加到瀑布流");
    } catch (error) {
      const message = error instanceof Error ? error.message : "添加失败";
      toast.error(message);
    }
  };

  return (
    <>
      <section className="minimal-page-shell minimal-image-shell mx-auto flex h-[calc(100dvh-4.75rem)] min-h-[520px] w-full max-w-[1440px] overflow-hidden rounded-none border border-transparent bg-background lg:rounded-xl lg:border-border">
        <AnimatePresence>
          {isSidebarOpen ? (
            <motion.button
              type="button"
              className="fixed inset-0 z-40 bg-black/35 lg:hidden"
              aria-label="关闭侧栏"
              onClick={() => setIsSidebarOpen(false)}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.18 }}
            />
          ) : null}
        </AnimatePresence>

        <motion.aside
          initial={false}
          animate={{
            width: isDesktopViewport
              ? isSidebarCollapsed
                ? 0
                : 280
              : "min(88vw, 320px)",
            opacity: isSidebarVisible ? 1 : 0,
            x: isDesktopViewport || isSidebarOpen ? 0 : "-100%",
          }}
          transition={sidebarTransition}
          className={cn(
            "image-chat-sidebar fixed inset-y-0 left-0 z-50 flex min-w-0 shrink-0 flex-col overflow-hidden border-r border-sidebar-border lg:static lg:z-auto lg:h-full",
            isSidebarVisible ? "pointer-events-auto" : "pointer-events-none",
            isDesktopViewport && isSidebarCollapsed ? "border-r-0" : "",
          )}
        >
          <div className="flex h-full w-[min(88vw,320px)] min-w-0 shrink-0 flex-col gap-2.5 p-2.5 lg:w-[280px]">
            <div className="flex items-center gap-2 px-1">
              <div className="min-w-0 flex-1 text-sm font-medium text-sidebar-foreground">
                会话历史
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="lg:hidden"
                onClick={() => setIsSidebarOpen(false)}
                aria-label="关闭侧栏"
              >
                <X className="size-4" />
              </Button>
            </div>

            <div className="min-h-0 flex-1 border-t border-sidebar-border pt-2 lg:overflow-y-auto lg:pr-1">
              {isLoadingHistory ? (
                <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取会话记录
                </div>
              ) : !hasLoadedHistory ? (
                <div className="py-2 text-sm leading-6 text-muted-foreground">
                  会话记录待读取
                </div>
              ) : conversations.length === 0 ? (
                <div className="py-2 text-sm leading-6 text-muted-foreground">
                  暂无记录
                </div>
              ) : (
                <div className="space-y-1">
                  {conversations.map((conversation) => {
                    const active = conversation.id === selectedConversationId;
                    const isLoadingDetail =
                      loadingConversationDetailId === conversation.id;
                    return (
                      <motion.div
                        key={conversation.id}
                        initial={
                          shouldReduceMotion
                            ? false
                            : { opacity: 0, y: 8 }
                        }
                        animate={{ opacity: 1, y: 0 }}
                        exit={
                          shouldReduceMotion
                            ? undefined
                            : { opacity: 0, y: -6 }
                        }
                        transition={listTransition}
                        className={cn(
                          "group relative w-full rounded-lg border px-2.5 py-2 text-left transition",
                          active
                            ? "border-sidebar-border bg-sidebar-accent text-sidebar-foreground"
                            : "border-transparent text-muted-foreground hover:bg-sidebar-accent",
                        )}
                      >
                        <button
                          type="button"
                          onClick={() =>
                            void handleSelectConversation(conversation)
                          }
                          className="block w-full pr-7 text-left"
                        >
                          <div className="flex items-center gap-2">
                            <div className="min-w-0 flex-1 truncate text-[13px] font-medium">
                              {conversation.title}
                            </div>
                            {isLoadingDetail ? (
                              <LoaderCircle className="size-3.5 shrink-0 animate-spin text-muted-foreground" />
                            ) : null}
                          </div>
                          <div className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                            <span>
                              {formatConversationTime(conversation.createdAt)}
                            </span>
                            <span>
                              {conversation.turnCount &&
                              conversation.turnCount > 1
                                ? `${conversation.turnCount} 轮`
                                : formatConversationStatus(conversation)}
                            </span>
                          </div>
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            void handleDeleteConversation(conversation.id)
                          }
                          className="absolute top-1.5 right-1.5 inline-flex size-6 items-center justify-center rounded-md text-muted-foreground opacity-100 transition hover:bg-muted hover:text-rose-600 lg:opacity-0 lg:group-hover:opacity-100"
                          aria-label="删除会话"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="border-t border-sidebar-border pt-2">
              <button
                type="button"
                onClick={() => setIsClearHistoryDialogOpen(true)}
                disabled={conversations.length === 0}
                className="flex h-10 w-full items-center justify-start gap-2 rounded-lg border border-rose-300 bg-rose-50 px-3 text-sm font-medium text-rose-700 transition hover:bg-rose-100 focus-visible:ring-4 focus-visible:ring-rose-300/30 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-45 dark:border-rose-900/70 dark:bg-rose-950/40 dark:text-rose-200 dark:hover:bg-rose-950/65"
                aria-label="清空历史记录"
              >
                <Trash2 className="size-4" />
                清空历史记录
              </button>
              <div className="mt-1 px-1 text-[11px] leading-5 text-muted-foreground">
                清空前会再次确认。
              </div>
            </div>
          </div>
        </motion.aside>

        <div className="image-chat-main flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-border px-3 py-2 sm:px-4">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="relative z-10 shrink-0"
                onClick={() => {
                  if (window.innerWidth >= 1024) {
                    setIsSidebarCollapsed((value) => !value);
                    return;
                  }
                  setIsSidebarOpen(true);
                }}
                aria-label="切换会话历史"
              >
                {isSidebarCollapsed ? (
                  <PanelLeftOpen className="size-4" />
                ) : (
                  <PanelLeftClose className="size-4" />
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="h-11 px-3"
                onClick={handleCreateDraft}
                aria-label="新建对话"
              >
                <MessageSquarePlus className="size-4" />
                <span className="hidden sm:inline">新建</span>
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="h-11 px-3"
                onClick={handleOpenImagePreferenceDialog}
                aria-label="配置"
              >
                <Settings2 className="size-4" />
                <span className="hidden sm:inline">配置</span>
              </Button>
              <div className="hidden min-w-0 truncate text-sm text-muted-foreground md:block">
                {formatImagePreferenceLabel(effectiveImagePreference)}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
              {isInspirationRailHidden ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="hidden size-9 lg:inline-flex"
                  onClick={() => setIsInspirationRailHidden(false)}
                  aria-label="显示画廊"
                  title="显示画廊"
                >
                  <PanelRightOpen className="size-4" />
                </Button>
              ) : null}
              <span className="hidden rounded-lg border border-border px-2 py-1 sm:inline">
                {availableQuota === null
                  ? "额度未知"
                  : `剩余 ${availableQuota}`}
              </span>
              <span className="rounded-lg border border-border px-2 py-1">
                {queueStatus
                  ? `${queueStatus.user.running} 运行`
                  : "队列同步中"}
              </span>
            </div>
          </div>

          <div
            ref={resultsViewportRef}
            className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6"
          >
            {!selectedConversation ? (
              <div className="flex min-h-full items-center justify-center px-1 text-center">
                <div className="w-full max-w-3xl px-4 py-8 sm:py-10">
                  <h1 className="minimal-heading text-3xl sm:text-4xl">
                    今天你想创造什么?
                  </h1>
                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    {emptyPromptSuggestions.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => applyPromptToComposer(item.prompt)}
                        className="max-w-full rounded-full border border-border bg-card px-3 py-1.5 text-left text-xs text-muted-foreground transition hover:border-primary/50 hover:bg-muted hover:text-foreground focus-visible:ring-4 focus-visible:ring-ring/20 focus-visible:outline-none sm:max-w-[260px]"
                        title={item.prompt}
                      >
                        <span className="line-clamp-1">
                          {item.promptPreview || item.prompt}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mx-auto flex w-full max-w-[900px] flex-col gap-6">
                {getConversationTurns(selectedConversation).map((turn) => (
                  <motion.div
                    key={turn.id}
                    className="space-y-4"
                    initial={shouldReduceMotion ? false : { opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={listTransition}
                  >
                    <div className="flex justify-end">
                      <div className="flex w-full max-w-full flex-col items-end gap-3 sm:max-w-[80%]">
                        {turn.inputImage ? (
                          <div className="w-full max-w-[640px] overflow-hidden rounded-xl border border-border bg-card shadow-sm">
                            <img
                              src={turn.inputImage.dataUrl}
                              alt={turn.inputImage.fileName || "参考图"}
                              className="block max-h-[48dvh] w-full object-contain"
                            />
                            <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
                              {turn.inputImage.fileName || "参考图"}
                            </div>
                          </div>
                        ) : null}
                        <div className="rounded-2xl bg-muted px-4 py-3 text-left text-sm leading-7 text-foreground sm:text-[15px] sm:leading-8">
                          {turn.prompt}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded-full bg-muted px-3 py-1">
                        {imageModelLabels[turn.model] || turn.model}
                      </span>
                      <span className="rounded-full bg-muted px-3 py-1">
                        {turn.count} 张
                      </span>
                      <span className="rounded-full bg-muted px-3 py-1">
                        {formatImageSizeLabel(turn.size || "auto")}
                      </span>
                      <span className="rounded-full bg-muted px-3 py-1">
                        {formatConversationTime(turn.createdAt)}
                      </span>
                    </div>

                    {(turn.status === "queued" ||
                      turn.status === "assigning_account" ||
                      turn.status === "running") &&
                    turn.id === selectedTurn?.id ? (
                      <div className="rounded-xl border border-border bg-card px-4 py-4">
                        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                          <LoaderCircle className="size-4 animate-spin" />
                          排队进度
                        </div>
                        <div className="mt-3 text-sm leading-6 text-foreground">
                          {currentQueueProgressText}
                        </div>
                      </div>
                    ) : null}

                    {turn.copiedText ? (
                      <div className="rounded-xl border border-border bg-card px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-xs font-medium text-muted-foreground">
                            可复制文本
                          </div>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8"
                            onClick={() => {
                              void navigator.clipboard.writeText(
                                turn.copiedText || "",
                              );
                              toast.success("文本已复制");
                            }}
                          >
                            <Copy className="size-4" />
                            复制
                          </Button>
                        </div>
                        <pre className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-foreground">
                          {turn.copiedText}
                        </pre>
                      </div>
                    ) : null}

                    {turn.status === "error" && turn.images.length === 0 ? (
                      <div className="flex flex-col gap-3 rounded-xl border border-rose-300/70 bg-rose-50 px-4 py-4 text-sm leading-6 text-rose-700 sm:flex-row sm:items-center sm:justify-between dark:bg-rose-950/30 dark:text-rose-200">
                        <span>{turn.error || "生成失败"}</span>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={isComposerGenerating}
                          onClick={() =>
                            void handleGenerateImage({
                              conversation: selectedConversation,
                              turn,
                            })
                          }
                          className="h-9 shrink-0 disabled:opacity-60"
                        >
                          {isComposerGenerating ? (
                            <LoaderCircle className="size-4 animate-spin" />
                          ) : (
                            <RotateCcw className="size-4" />
                          )}
                          重试
                        </Button>
                      </div>
                    ) : null}

                    {turn.images.length > 0 ? (
                      <div
                        className={cn(
                          "grid gap-4",
                          turn.images.length === 1
                            ? "grid-cols-1"
                            : "grid-cols-1 sm:grid-cols-2",
                        )}
                      >
                        {turn.images.map((image, index) => {
                          const isSuccessImage =
                            image.status === "success" && Boolean(image.b64_json);
                          const waterfallSourceImageId = buildWaterfallSourceImageId(
                            selectedConversation.id,
                            turn.id,
                            image.id,
                          );
                          const isAlreadyInWaterfall =
                            userWaterfallSourceImageIds.has(
                              waterfallSourceImageId,
                            );
                          return (
                            <motion.div
                              key={image.id}
                              layout
                              initial={
                                shouldReduceMotion
                                  ? false
                                  : { opacity: 0, y: 14, scale: 0.98 }
                              }
                              animate={{ opacity: 1, y: 0, scale: 1 }}
                              transition={listTransition}
                              className="overflow-hidden rounded-xl"
                            >
                              {isSuccessImage && image.b64_json ? (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => handleOpenPreview(image.id)}
                                    className="group flex w-full items-center justify-center overflow-hidden rounded-xl bg-muted text-left"
                                    aria-label={`预览第 ${index + 1} 张图片`}
                                  >
                                    <img
                                      src={buildImageDataUrl(
                                        image.b64_json,
                                        image.mimeType,
                                      )}
                                      alt={`Generated result ${index + 1}`}
                                      loading="lazy"
                                      className={cn(
                                        "block h-auto w-full object-contain transition duration-200 group-hover:scale-[1.01]",
                                        turn.images.length === 1
                                          ? "max-h-[72dvh]"
                                          : "max-h-[54dvh]",
                                      )}
                                    />
                                  </button>
                                  <div className="flex justify-end px-1 pt-2">
                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="sm"
                                      disabled={isAlreadyInWaterfall}
                                      className="h-8 rounded-full px-3 text-xs disabled:opacity-70"
                                      onClick={() =>
                                        void handleAddImageToWaterfall(
                                          selectedConversation,
                                          turn,
                                          image,
                                        )
                                      }
                                    >
                                      <CirclePlus className="size-3.5" />
                                      {isAlreadyInWaterfall
                                        ? "已在瀑布流"
                                        : "添加到瀑布流"}
                                    </Button>
                                  </div>
                                </>
                              ) : image.status === "error" ? (
                                <div
                                  className={cn(
                                    "flex items-center justify-center bg-rose-50 px-6 py-8 text-center text-sm leading-6 text-rose-700 dark:bg-rose-950/30 dark:text-rose-200",
                                    turn.images.length === 1
                                      ? "min-h-[min(520px,60dvh)]"
                                      : "min-h-[280px]",
                                  )}
                                >
                                  {image.error || "生成失败"}
                                </div>
                              ) : (
                                <div
                                  className={cn(
                                    "flex flex-col items-center justify-center gap-3 bg-muted px-6 py-8 text-center text-muted-foreground",
                                    turn.images.length === 1
                                      ? "min-h-[min(520px,60dvh)]"
                                      : "min-h-[280px]",
                                  )}
                                >
                                  <div className="rounded-full bg-background p-3 shadow-sm">
                                    <LoaderCircle className="size-5 animate-spin" />
                                  </div>
                                  <p className="text-sm">正在生成图片...</p>
                                </div>
                              )}
                            </motion.div>
                          );
                        })}
                      </div>
                    ) : null}

                    {turn.status === "error" && turn.images.length > 0 ? (
                      <div className="flex flex-col gap-3 rounded-xl border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800 sm:flex-row sm:items-center sm:justify-between dark:bg-amber-950/30 dark:text-amber-100">
                        <span>{turn.error}</span>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={isComposerGenerating}
                          onClick={() =>
                            void handleGenerateImage({
                              conversation: selectedConversation,
                              turn,
                            })
                          }
                          className="h-9 shrink-0 disabled:opacity-60"
                        >
                          {isComposerGenerating ? (
                            <LoaderCircle className="size-4 animate-spin" />
                          ) : (
                            <RotateCcw className="size-4" />
                          )}
                          重试
                        </Button>
                      </div>
                    ) : null}
                  </motion.div>
                ))}
              </div>
            )}
          </div>

          <div className="shrink-0 border-t border-border bg-background/95 px-3 py-3 sm:px-6">
            <motion.div
              className="image-composer mx-auto max-h-[42dvh] w-full max-w-[900px] overflow-y-auto rounded-[28px] border px-3 pt-3 pb-2 transition focus-within:border-ring focus-within:ring-4 focus-within:ring-ring/15 sm:px-4 sm:pt-4 sm:pb-3"
              initial={shouldReduceMotion ? false : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={listTransition}
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
                <div className="mb-3 flex items-start gap-3 rounded-xl border border-border bg-muted px-3 py-3">
                  <img
                    src={inputImage.dataUrl}
                    alt={inputImage.fileName}
                    className="h-20 w-24 shrink-0 rounded-xl bg-background object-contain sm:h-24 sm:w-32"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-foreground">
                      {inputImage.fileName}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
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
                    className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-background hover:text-foreground"
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
                className="h-auto max-h-[22dvh] min-h-12 w-full resize-none overflow-y-auto rounded-none border-0 bg-transparent px-1 py-2 text-base leading-7 shadow-none placeholder:text-muted-foreground focus-visible:ring-0 sm:px-2 sm:py-3"
              />

              <div className="mt-1 flex flex-wrap items-center gap-2 border-t border-border/60 pt-2 sm:flex-nowrap">
                <button
                  type="button"
                  onClick={handleOpenInputImagePicker}
                  disabled={isUploadingInputImage}
                  title={
                    inputImage
                      ? "更换参考图"
                      : isUploadingInputImage
                        ? "图片上传中"
                        : "上传参考图"
                  }
                  className={cn(
                    "inline-flex size-10 shrink-0 items-center justify-center rounded-full border transition focus-visible:ring-4 focus-visible:ring-ring/20 focus-visible:outline-none",
                    inputImage
                      ? "border-primary bg-muted text-foreground"
                      : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
                    isUploadingInputImage
                      ? "cursor-not-allowed opacity-60"
                      : "",
                  )}
                  aria-label={
                    inputImage
                      ? "更换参考图"
                      : isUploadingInputImage
                        ? "图片上传中"
                        : "上传参考图"
                  }
                >
                  {isUploadingInputImage ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <CirclePlus className="size-5" />
                  )}
                </button>

                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  className="size-10 shrink-0 rounded-full"
                  title="打开画廊"
                  aria-label="打开画廊"
                  asChild
                >
                  <Link href="/gallery">
                    <Images className="size-4" />
                  </Link>
                </Button>

                <div className="flex shrink-0 items-center gap-1 rounded-2xl border border-border bg-background p-1">
                  {PRIMARY_IMAGE_COUNT_OPTIONS.map((count) => {
                    const active = imageCount === count;
                    return (
                      <button
                        key={count}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setImageCount(count)}
                        className={cn(
                          "h-8 min-w-9 cursor-pointer rounded-full px-2 text-sm transition focus-visible:ring-4 focus-visible:ring-ring/20 focus-visible:outline-none",
                          active
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground",
                        )}
                      >
                        {count} 张
                      </button>
                    );
                  })}
                  <label className="sr-only" htmlFor="image-count-input">
                    生成图片张数
                  </label>
                  <input
                    id="image-count-input"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={MAX_IMAGES_PER_REQUEST}
                    value={imageCount}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => setImageCount(event.target.value)}
                    onBlur={() => setImageCount(String(parsedCount))}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.currentTarget.blur();
                      }
                    }}
                    className="h-8 w-14 rounded-full border border-border bg-background px-2 text-center text-sm text-foreground outline-none transition focus:border-ring focus:ring-4 focus:ring-ring/20"
                    aria-label={`生成图片张数，范围 1 到 ${MAX_IMAGES_PER_REQUEST}`}
                  />
                </div>

                <div
                  className={cn(
                    "hidden min-w-0 flex-1 truncate px-1 text-xs sm:block",
                    isQuotaInsufficient
                      ? "text-rose-600 dark:text-rose-300"
                      : "text-muted-foreground",
                  )}
                >
                  {composerStatusText}
                </div>

                {interruptedRequestCount > 0 ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-10 shrink-0 rounded-full px-3"
                    onClick={() => {
                      void handleResetInterruptedRequests();
                    }}
                  >
                    <RotateCcw className="size-4" />
                    重置
                  </Button>
                ) : null}

                <Button
                  type="button"
                  onClick={() => void handleGenerateImage()}
                  disabled={
                    isComposerGenerating ||
                    isQuotaInsufficient ||
                    isUploadingInputImage
                  }
                  className="ml-auto size-10 shrink-0 rounded-full p-0 disabled:opacity-50"
                  aria-label="发送"
                >
                  {isComposerGenerating ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <ArrowUp className="size-4" />
                  )}
                </Button>
              </div>
              <div
                className={cn(
                  "px-1 pt-2 text-xs leading-5 sm:hidden",
                  isQuotaInsufficient
                    ? "text-rose-600 dark:text-rose-300"
                    : "text-muted-foreground",
                )}
              >
                {composerStatusText}
              </div>
            </motion.div>
          </div>
        </div>

        <ImageInspirationRail
          items={rankedGalleryItems}
          imageDimensions={galleryImageDimensions}
          isHidden={isInspirationRailHidden}
          isLoading={isGalleryDataLoading}
          shouldReduceMotion={Boolean(shouldReduceMotion)}
          onHide={() => setIsInspirationRailHidden(true)}
          onOpenPreview={setGalleryPreviewItem}
        />
      </section>

      <Dialog
        open={isClearHistoryDialogOpen}
        onOpenChange={setIsClearHistoryDialogOpen}
      >
        <DialogContent className="w-[min(92vw,440px)] p-5">
          <DialogTitle>确认清空历史记录</DialogTitle>
          <DialogDescription>
            此操作会删除当前密钥下保存的全部图片会话历史，删除后无法在页面内恢复。
          </DialogDescription>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsClearHistoryDialogOpen(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              className="border border-rose-700 bg-rose-600 text-white hover:bg-rose-700"
              onClick={() => void handleClearHistory()}
            >
              <Trash2 className="size-4" />
              确认清空
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={isSizeDialogOpen} onOpenChange={setIsSizeDialogOpen}>
        <DialogContent className="w-[min(94vw,520px)] p-5">
          <DialogTitle className="sr-only">画面配置</DialogTitle>
          <div className="space-y-5">
            <div>
              <div className="text-sm font-semibold">画面配置</div>
              <div className="mt-1 text-xs text-muted-foreground">
                当前：{formatImagePreferenceLabel(effectiveImagePreference)}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">控制方式</div>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { value: "auto" as const, label: "自动" },
                  { value: "resolution" as const, label: "分辨率" },
                  { value: "ratio" as const, label: "比例" },
                ].map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => {
                      setSizeDraftMode(item.value);
                      setSizeDraft((prev) => {
                        if (item.value === "auto") {
                          return { ...DEFAULT_IMAGE_GENERATION_PREFERENCE };
                        }
                        if (item.value === "resolution") {
                          return {
                            resolution:
                              prev.resolution === IMAGE_RESOLUTION_AUTO
                                ? "1k"
                                : prev.resolution,
                            ratio: "auto",
                          };
                        }
                        return {
                          resolution: IMAGE_RESOLUTION_AUTO,
                          ratio: prev.ratio === "auto" ? "1:1" : prev.ratio,
                        };
                      });
                    }}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-sm transition",
                      sizeDraftMode === item.value
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-foreground hover:bg-muted",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">画面分辨率</div>
              <div className="grid grid-cols-3 gap-2">
                {IMAGE_RESOLUTION_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    type="button"
                    disabled={sizeDraftMode !== "resolution"}
                    onClick={() => {
                      setSizeDraftMode("resolution");
                      setSizeDraft((prev) => ({
                        resolution: preset.value,
                        ratio: "auto",
                      }));
                    }}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-45",
                      sizeDraftMode === "resolution" &&
                        sizeDraft.resolution === preset.value
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-foreground hover:bg-muted",
                    )}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">图片比例</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {IMAGE_ASPECT_RATIO_PRESETS.filter(
                  (preset) => preset.value !== "auto",
                ).map((preset) => (
                  <button
                    key={preset.value}
                    type="button"
                    disabled={sizeDraftMode !== "ratio"}
                    onClick={() => {
                      setSizeDraftMode("ratio");
                      setSizeDraft((prev) => ({
                        resolution: IMAGE_RESOLUTION_AUTO,
                        ratio: preset.value,
                      }));
                    }}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-45",
                      sizeDraftMode === "ratio" &&
                        sizeDraft.ratio === preset.value
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-background text-foreground hover:bg-muted",
                    )}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground">
              本次将使用：{formatImagePreferenceLabel(normalizedSizeDraft)}
            </div>

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIsSizeDialogOpen(false)}
              >
                取消
              </Button>
              <Button type="button" onClick={() => void handleApplyImageSize()}>
                保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(previewImage)}
        onOpenChange={(open) => (!open ? setPreviewImageId(null) : null)}
      >
        <DialogContent className="w-[min(96vw,1120px)] p-2 sm:p-4">
          <DialogTitle className="sr-only">图片预览</DialogTitle>
          {previewImage ? (
            <div className="space-y-3">
              <div className="flex flex-col gap-3 rounded-xl bg-muted px-3 py-2 text-sm text-foreground sm:flex-row sm:items-center sm:justify-between sm:px-4">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <span className="rounded-full bg-background px-3 py-1 text-xs font-medium">
                    {previewImageIndex + 1} / {previewableImages.length}
                  </span>
                  <span className="hidden text-xs text-muted-foreground sm:inline">
                    当前会话成功图片预览
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={handleDownloadPreviewImage}
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
                  >
                    下一张
                    <ArrowRight className="size-4" />
                  </Button>
                </div>
              </div>

              <div className="flex items-center justify-center overflow-hidden rounded-xl bg-muted">
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

      <Dialog
        open={Boolean(galleryPreviewItem)}
        onOpenChange={(open) => {
          if (!open) {
            setGalleryPreviewItem(null);
          }
        }}
      >
        <DialogContent className="w-[min(96vw,1180px)] p-2 sm:p-4">
          <DialogTitle className="sr-only">画廊图片预览</DialogTitle>
          {galleryPreviewItem ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_340px]">
              <div className="flex items-center justify-center overflow-hidden rounded-xl bg-muted">
                <img
                  src={galleryPreviewItem.imageUrl}
                  alt={galleryPreviewItem.title}
                  className="h-auto max-h-[82vh] w-auto max-w-full object-contain"
                />
              </div>

              <div className="minimal-panel-soft flex min-h-0 flex-col p-4">
                <div className="min-w-0">
                  <div className="text-base font-semibold text-foreground">
                    {galleryPreviewItem.isUserGenerated
                      ? "我的作品"
                      : `第 ${galleryPreviewItem.postNumber} 层 / @${galleryPreviewItem.username}`}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {galleryPreviewItem.title}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={async () => {
                      if (!galleryPreviewItem.hasPrompt) {
                        toast.error("这张图没有 prompt");
                        return;
                      }
                      try {
                        await navigator.clipboard.writeText(
                          galleryPreviewItem.prompt,
                        );
                        toast.success("prompt 已复制");
                      } catch {
                        toast.error("复制失败");
                      }
                    }}
                  >
                    <Copy className="size-4" />
                    复制 prompt
                  </Button>
                  {galleryPreviewItem.hasPrompt ? (
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => {
                        applyPromptToComposer(galleryPreviewItem.prompt);
                        setGalleryPreviewItem(null);
                      }}
                    >
                      带入 prompt
                    </Button>
                  ) : null}
                </div>

                <div
                  className={cn(
                    "mt-4 min-h-0 flex-1 overflow-y-auto rounded-lg border px-4 py-4 text-left text-sm leading-6",
                    galleryPreviewItem.hasPrompt
                      ? "border-border bg-muted/45 text-foreground"
                      : "border-border bg-muted/35 text-muted-foreground",
                  )}
                >
                  <div className="whitespace-pre-wrap">
                    {galleryPreviewItem.hasPrompt
                      ? galleryPreviewItem.prompt
                      : "未提供"}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
