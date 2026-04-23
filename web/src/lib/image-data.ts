"use client";

const PNG_PREFIX = "iVBORw0KGgo";
const JPEG_PREFIX = "/9j/";
const WEBP_PREFIX = "UklGR";
const GIF_PREFIX = "R0lGOD";
const BMP_PREFIX = "Qk";
const AVIF_PREFIX = "AAAAIGZ0eXBhdmlm";

export function detectImageMimeType(base64: string): string {
  const normalized = String(base64 || "").trim();
  if (!normalized) {
    return "image/png";
  }
  if (normalized.startsWith(PNG_PREFIX)) {
    return "image/png";
  }
  if (normalized.startsWith(JPEG_PREFIX)) {
    return "image/jpeg";
  }
  if (normalized.startsWith(WEBP_PREFIX)) {
    return "image/webp";
  }
  if (normalized.startsWith(GIF_PREFIX)) {
    return "image/gif";
  }
  if (normalized.startsWith(BMP_PREFIX)) {
    return "image/bmp";
  }
  if (normalized.startsWith(AVIF_PREFIX)) {
    return "image/avif";
  }
  return "image/png";
}

export function buildImageDataUrl(base64: string, mimeType?: string): string {
  const resolvedMimeType = String(mimeType || "").trim() || detectImageMimeType(base64);
  return `data:${resolvedMimeType};base64,${String(base64 || "").trim()}`;
}

export function detectImageFileExtension(base64: string, mimeType?: string): string {
  const resolvedMimeType = String(mimeType || "").trim() || detectImageMimeType(base64);
  switch (resolvedMimeType) {
    case "image/jpeg":
      return "jpg";
    case "image/webp":
      return "webp";
    case "image/gif":
      return "gif";
    case "image/bmp":
      return "bmp";
    case "image/avif":
      return "avif";
    default:
      return "png";
  }
}
