"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Expand, LoaderCircle, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type GallerySeedItem = {
  id: number;
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
};

type GalleryImageDimension = {
  id: number;
  width: number;
  height: number;
  aspectRatio: number;
};

type ImageGalleryPanelProps = {
  onApplyPrompt: (prompt: string) => void;
  promptTargetHref?: string;
};

const INITIAL_RENDER_COUNT = 24;
const RENDER_CHUNK_SIZE = 24;
const IMAGE_PRELOAD_MARGIN = "1400px 0px";
const DEFAULT_ASPECT_RATIO = 0.8;

function normalizeSearchText(value: string) {
  return value.trim().toLowerCase();
}

function GalleryCard({
  item,
  imageDimension,
  onOpenImage,
}: {
  item: GallerySeedItem;
  imageDimension?: GalleryImageDimension;
  onOpenImage: (item: GallerySeedItem) => void;
  onApplyPrompt: (prompt: string) => void;
  promptTargetHref?: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [canRenderImage, setCanRenderImage] = useState(false);
  const [isImageReady, setIsImageReady] = useState(false);
  const aspectRatio = imageDimension?.aspectRatio || DEFAULT_ASPECT_RATIO;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setCanRenderImage(true);
            observer.disconnect();
            break;
          }
        }
      },
      { rootMargin: IMAGE_PRELOAD_MARGIN },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!canRenderImage) {
      return;
    }
    let cancelled = false;
    const image = new Image();
    image.src = item.imageUrl;
    const markReady = () => {
      if (!cancelled) {
        setIsImageReady(true);
      }
    };
    if (image.decode) {
      image.decode().then(markReady).catch(markReady);
    } else {
      image.onload = markReady;
      image.onerror = markReady;
    }
    return () => {
      cancelled = true;
    };
  }, [canRenderImage, item.imageUrl]);

  return (
    <article
      ref={containerRef}
      className="group minimal-panel-soft break-inside-avoid overflow-hidden rounded-[18px] border-white/8 bg-[rgba(18,18,26,0.72)]"
    >
      <div className="relative">
        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="relative block w-full overflow-hidden bg-[#0d0d13] text-left"
          style={{ aspectRatio: String(aspectRatio) }}
          aria-label={`放大查看第 ${item.postNumber} 层图片`}
        >
          <div className="absolute inset-0 animate-pulse bg-[linear-gradient(180deg,rgba(255,255,255,0.03),rgba(255,255,255,0.015))]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(245,158,11,0.08),transparent_55%)]" />
          {canRenderImage ? (
            <img
              src={item.imageUrl}
              alt={item.title}
              loading="lazy"
              decoding="async"
              width={imageDimension?.width}
              height={imageDimension?.height}
              className={cn(
                "absolute inset-0 block h-full w-full object-cover transition duration-500 will-change-transform",
                isImageReady
                  ? "opacity-100 group-hover:scale-[1.015]"
                  : "opacity-0",
              )}
            />
          ) : null}
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_48%,rgba(7,7,10,0.2)_78%,rgba(7,7,10,0.56)_100%)]" />
          <div className="absolute top-3 left-3 flex flex-wrap gap-2">
            <span className="rounded-full border border-white/12 bg-black/45 px-2.5 py-1 text-[11px] text-stone-200 backdrop-blur">
              #{item.postNumber}
            </span>
            <span className="rounded-full border border-white/12 bg-black/45 px-2.5 py-1 text-[11px] text-stone-300 backdrop-blur">
              @{item.username}
            </span>
          </div>
          <span className="absolute right-3 bottom-3 inline-flex size-9 items-center justify-center rounded-full border border-white/12 bg-amber-400 text-stone-950 shadow-[0_0_24px_rgba(245,158,11,0.26)]">
            <Expand className="size-4" />
          </span>
        </button>
      </div>

      <div className="space-y-3 px-3 py-3">
        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="flex w-full items-start justify-between gap-3 rounded-2xl px-1 py-1 text-left transition hover:bg-white/[0.035]"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-stone-100">
              第 {item.postNumber} 层 / 图 {item.imageIndex}
            </div>
            <div className="mt-1 text-xs text-stone-500">{item.title}</div>
          </div>
          <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full text-stone-500">
            <Sparkles className="size-4" />
          </span>
        </button>

        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="block w-full rounded-2xl border border-white/8 bg-white/[0.025] px-3 py-3 text-left transition hover:border-white/14 hover:bg-white/[0.045]"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-stone-500">
              Prompt
            </div>
            <span className="text-[11px] text-stone-500">点击预览</span>
          </div>
          <div className="line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-stone-300">
            {item.hasPrompt ? item.promptPreview || item.prompt : "未提供"}
          </div>
        </button>
      </div>
    </article>
  );
}

export function ImageGalleryPanel({
  onApplyPrompt,
  promptTargetHref,
}: ImageGalleryPanelProps) {
  const router = useRouter();
  const [items, setItems] = useState<GallerySeedItem[]>([]);
  const [imageDimensions, setImageDimensions] = useState<
    Record<number, GalleryImageDimension>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [renderCount, setRenderCount] = useState(INITIAL_RENDER_COUNT);
  const [previewItem, setPreviewItem] = useState<GallerySeedItem | null>(null);
  const [isPreviewPromptExpanded, setIsPreviewPromptExpanded] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        const [itemsMod, dimensionsMod] = await Promise.all([
          import("@/data/gallery-ui-seed.json"),
          import("@/data/gallery-image-dimensions.json").catch(() => ({
            default: [],
          })),
        ]);
        if (!cancelled) {
          setItems((itemsMod.default || []) as GallerySeedItem[]);
          const nextDimensions = Object.fromEntries(
            ((dimensionsMod.default || []) as GalleryImageDimension[]).map(
              (item) => [item.id, item],
            ),
          );
          setImageDimensions(nextDimensions);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredItems = useMemo(() => {
    const q = normalizeSearchText(keyword);
    if (!q) {
      return items;
    }
    return items.filter((item) =>
      normalizeSearchText(
        `${item.postNumber} ${item.username} ${item.title} ${item.prompt}`,
      ).includes(q),
    );
  }, [items, keyword]);

  useEffect(() => {
    const element = sentinelRef.current;
    if (!element) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setRenderCount((count) =>
              Math.min(count + RENDER_CHUNK_SIZE, filteredItems.length),
            );
          }
        }
      },
      { rootMargin: "2000px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [filteredItems.length]);

  const visibleItems = filteredItems.slice(0, renderCount);
  const previewPromptText = previewItem?.hasPrompt ? previewItem.prompt : "未提供";
  const shouldClampPreviewPrompt =
    Boolean(previewItem?.hasPrompt) && previewPromptText.length > 320;

  const handleApplyPrompt = (prompt: string) => {
    const normalizedPrompt = String(prompt || "").trim();
    if (!normalizedPrompt) {
      toast.error("这张图没有 prompt");
      return;
    }
    onApplyPrompt(normalizedPrompt);
    if (promptTargetHref) {
      router.push(
        `${promptTargetHref}?prompt=${encodeURIComponent(normalizedPrompt)}&focus=prompt`,
      );
      return;
    }
    toast.success("已填入 prompt");
  };

  return (
    <>
      <section className="minimal-panel min-h-0 overflow-hidden rounded-[26px] border-white/10 bg-[rgba(13,13,19,0.84)]">
        <div className="border-b border-white/8 px-4 py-4 sm:px-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-stone-100">灵感画廊</div>
              <div className="mt-1 text-xs text-stone-500">
                图片与 prompt 一起展示，点图放大，点 prompt 区域可展开和复制。
              </div>
            </div>
            <div className="rounded-full border border-white/8 bg-white/[0.04] px-3 py-1 text-xs text-stone-400">
              {isLoading ? "加载中" : `${filteredItems.length} 张`}
            </div>
          </div>

          <label className="mt-4 flex items-center gap-2 rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-2">
            <Search className="size-4 text-stone-500" />
            <input
              value={keyword}
              onChange={(event) => {
                setKeyword(event.target.value);
                setRenderCount(INITIAL_RENDER_COUNT);
              }}
              placeholder="搜索楼层 / 用户 / prompt"
              className="w-full border-0 bg-transparent text-sm text-stone-100 outline-none placeholder:text-stone-500"
            />
          </label>
        </div>

        <div className="hide-scrollbar h-[58vh] overflow-y-auto px-3 py-3 sm:px-4">
          {isLoading ? (
            <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-stone-400">
              <LoaderCircle className="size-4 animate-spin" />
              正在加载画廊
            </div>
          ) : visibleItems.length === 0 ? (
            <div className="flex min-h-[220px] items-center justify-center text-sm text-stone-500">
              没有匹配结果
            </div>
          ) : (
            <div className="columns-1 gap-4 space-y-4 md:columns-2 2xl:columns-3">
              {visibleItems.map((item) => (
                <GalleryCard
                  key={item.id}
                  item={item}
                  imageDimension={imageDimensions[item.id]}
                  onOpenImage={setPreviewItem}
                  onApplyPrompt={handleApplyPrompt}
                  promptTargetHref={promptTargetHref}
                />
              ))}
            </div>
          )}
          <div ref={sentinelRef} className="h-8 w-full" />
        </div>
      </section>

      <Dialog
        open={Boolean(previewItem)}
        onOpenChange={(open) => {
          if (!open) {
            setPreviewItem(null);
            setIsPreviewPromptExpanded(false);
          }
        }}
      >
        <DialogContent className="w-[min(96vw,1280px)] bg-[rgba(10,10,15,0.97)] p-2 sm:p-4">
          {previewItem ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_380px]">
              <div className="flex items-center justify-center overflow-hidden rounded-[22px] bg-black/60">
                <img
                  src={previewItem.imageUrl}
                  alt={previewItem.title}
                  className="h-auto max-h-[84vh] w-auto max-w-full object-contain"
                />
              </div>

              <div className="minimal-panel-soft flex min-h-0 flex-col rounded-[22px] border-white/8 bg-white/[0.03] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-base font-semibold text-stone-100">
                      第 {previewItem.postNumber} 层 / @{previewItem.username}
                    </div>
                    <div className="mt-1 text-xs text-stone-500">{previewItem.title}</div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="rounded-full border-white/12 bg-white/[0.03] text-stone-100 hover:bg-white/[0.08]"
                    onClick={async () => {
                      if (!previewItem.hasPrompt) {
                        toast.error("这张图没有 prompt");
                        return;
                      }
                      try {
                        await navigator.clipboard.writeText(previewItem.prompt);
                        toast.success("prompt 已复制");
                      } catch {
                        toast.error("复制失败");
                      }
                    }}
                  >
                    <Copy className="size-4" />
                    复制
                  </Button>
                </div>
                {previewItem.hasPrompt && promptTargetHref ? (
                  <Link
                    href={`${promptTargetHref}?prompt=${encodeURIComponent(previewItem.prompt)}&focus=prompt`}
                    className="mt-3 inline-flex h-9 items-center rounded-full border border-white/12 bg-white/[0.03] px-4 text-sm text-stone-100 transition hover:bg-white/[0.08]"
                  >
                    带到画图页
                  </Link>
                ) : null}

                <div
                  className={cn(
                    "mt-4 min-h-0 flex-1 overflow-y-auto rounded-[18px] border px-4 py-4 text-left text-sm leading-6",
                    previewItem.hasPrompt
                      ? "border-white/8 bg-black/16 text-stone-200"
                      : "cursor-not-allowed border-white/6 bg-black/12 text-stone-500",
                  )}
                >
                  <div
                    className={cn(
                      "whitespace-pre-wrap",
                      shouldClampPreviewPrompt && !isPreviewPromptExpanded
                        ? "line-clamp-[12]"
                        : "",
                    )}
                  >
                    {previewPromptText}
                  </div>
                </div>

                {shouldClampPreviewPrompt ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="mt-3 h-9 rounded-full border-white/12 bg-white/[0.03] text-stone-100 hover:bg-white/[0.08]"
                    onClick={() =>
                      setIsPreviewPromptExpanded((value) => !value)
                    }
                  >
                    {isPreviewPromptExpanded ? "收起" : "展开完整提示词"}
                  </Button>
                ) : null}

                {previewItem.hasPrompt ? (
                  <Button
                    type="button"
                    className="mt-4 h-10 rounded-full"
                    onClick={() => handleApplyPrompt(previewItem.prompt)}
                  >
                    带入当前 prompt
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
