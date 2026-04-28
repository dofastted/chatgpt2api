"use client";

import { ImageGalleryPanel } from "@/components/image-gallery-panel";

export default function GalleryPage() {
  return (
    <section className="minimal-page-shell mx-auto w-full max-w-[1680px] pb-4">
      <div className="mb-4 px-1 sm:px-0">
        <h1 className="minimal-heading text-3xl sm:text-4xl">
          图片画廊
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          点击图片放大。点击 prompt 区域展开全文，右上角可以复制，也可以直接带回画图页。
        </p>
      </div>

      <ImageGalleryPanel
        onApplyPrompt={() => {}}
        promptTargetHref="/image"
      />
    </section>
  );
}
