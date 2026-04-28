"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Copy, Expand, LoaderCircle, Search, Sparkles } from "lucide-react";
import NextImage from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
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
    const image = new window.Image();
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
      className="group overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="relative">
        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="relative block w-full overflow-hidden bg-muted text-left"
          style={{ aspectRatio: String(aspectRatio) }}
          aria-label={`放大查看第 ${item.postNumber} 层图片`}
        >
          <div className="absolute inset-0 animate-pulse bg-muted" />
          {canRenderImage ? (
            <NextImage
              src={item.imageUrl}
              alt={item.title}
              fill
              unoptimized
              sizes="(min-width: 1536px) 25vw, (min-width: 1280px) 33vw, (min-width: 768px) 50vw, 100vw"
              className={cn(
                "object-cover transition duration-500 will-change-transform",
                isImageReady
                  ? "opacity-100 group-hover:scale-[1.015]"
                  : "opacity-0",
              )}
            />
          ) : null}
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_48%,rgba(7,7,10,0.2)_78%,rgba(7,7,10,0.56)_100%)]" />
          <div className="absolute top-3 left-3 flex flex-wrap gap-2">
            <span className="rounded-full border border-white/20 bg-black/55 px-2.5 py-1 text-[11px] text-white backdrop-blur">
              #{item.postNumber}
            </span>
            <span className="rounded-full border border-white/20 bg-black/55 px-2.5 py-1 text-[11px] text-white backdrop-blur">
              @{item.username}
            </span>
          </div>
          <span className="absolute right-3 bottom-3 inline-flex size-9 items-center justify-center rounded-full border border-border bg-background text-foreground shadow-sm">
            <Expand className="size-4" />
          </span>
        </button>
      </div>

      <div className="space-y-3 px-3 py-3">
        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="flex w-full items-start justify-between gap-3 rounded-lg px-1 py-1 text-left transition hover:bg-muted"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-foreground">
              第 {item.postNumber} 层 / 图 {item.imageIndex}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {item.title}
            </div>
          </div>
          <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground">
            <Sparkles className="size-4" />
          </span>
        </button>

        <button
          type="button"
          onClick={() => onOpenImage(item)}
          className="block w-full rounded-lg border border-border bg-muted/45 px-3 py-3 text-left transition hover:bg-muted"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-[11px] text-muted-foreground">Prompt</div>
            <span className="text-[11px] text-muted-foreground">点击预览</span>
          </div>
          <div className="line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-foreground">
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
  const previewPromptText = previewItem?.hasPrompt
    ? previewItem.prompt
    : "未提供";
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
      <section className="minimal-panel min-h-0 overflow-hidden">
        <div className="border-b border-border px-4 py-4 sm:px-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-foreground">
                灵感画廊
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                图片与 prompt 一起展示，点图放大，点 prompt 区域可展开和复制。
              </div>
            </div>
            <div className="rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground">
              {isLoading ? "加载中" : `${filteredItems.length} 张`}
            </div>
          </div>

          <label className="mt-4 flex h-11 items-center gap-2 rounded-lg border border-border bg-background px-3">
            <Search className="size-4 text-muted-foreground" />
            <input
              value={keyword}
              onChange={(event) => {
                setKeyword(event.target.value);
                setRenderCount(INITIAL_RENDER_COUNT);
              }}
              placeholder="搜索楼层 / 用户 / prompt"
              className="w-full border-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>
        </div>

        <div className="hide-scrollbar max-h-[calc(100dvh-14rem)] overflow-y-auto px-3 py-3 sm:px-4">
          {isLoading ? (
            <div className="flex min-h-[240px] items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" />
              正在加载画廊
            </div>
          ) : visibleItems.length === 0 ? (
            <div className="flex min-h-[220px] items-center justify-center text-sm text-muted-foreground">
              没有匹配结果
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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
        <DialogContent className="w-[min(96vw,1280px)] p-2 sm:p-4">
          <DialogTitle className="sr-only">画廊图片预览</DialogTitle>
          {previewItem ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_380px]">
              <div className="flex items-center justify-center overflow-hidden rounded-xl bg-muted">
                <NextImage
                  src={previewItem.imageUrl}
                  alt={previewItem.title}
                  width={imageDimensions[previewItem.id]?.width || 1200}
                  height={imageDimensions[previewItem.id]?.height || 1200}
                  unoptimized
                  sizes="min(96vw, 900px)"
                  className="h-auto max-h-[84vh] w-auto max-w-full object-contain"
                />
              </div>

              <div className="minimal-panel-soft flex min-h-0 flex-col p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-base font-semibold text-foreground">
                      第 {previewItem.postNumber} 层 / @{previewItem.username}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {previewItem.title}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="rounded-lg"
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
                    className="mt-3 inline-flex h-9 items-center rounded-lg border border-border bg-background px-4 text-sm text-foreground transition hover:bg-muted"
                  >
                    带到画图页
                  </Link>
                ) : null}

                <div
                  className={cn(
                    "mt-4 min-h-0 flex-1 overflow-y-auto rounded-[18px] border px-4 py-4 text-left text-sm leading-6",
                    previewItem.hasPrompt
                      ? "border-border bg-muted/45 text-foreground"
                      : "cursor-not-allowed border-border bg-muted/35 text-muted-foreground",
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
                    className="mt-3 h-9 rounded-lg"
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
                    className="mt-4 h-10 rounded-lg"
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
