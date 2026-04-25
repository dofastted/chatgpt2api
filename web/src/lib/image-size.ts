export const IMAGE_SIZE_AUTO = "auto";

const MIN_IMAGE_SIZE = 16;
const MAX_IMAGE_SIZE = 4096;
const DEFAULT_AREA = 1024 * 1024;

export type ImageSizeMode = "auto" | "ratio" | "custom";

export type ImageSizeSelection = {
  mode: ImageSizeMode;
  value: string;
  ratio?: string;
  width?: number;
  height?: number;
};

function roundDownToMultiple(value: number, multiple = 16) {
  return Math.max(MIN_IMAGE_SIZE, Math.floor(Math.max(MIN_IMAGE_SIZE, value) / multiple) * multiple);
}

export function normalizeImageSize(value: string | null | undefined) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized || normalized === IMAGE_SIZE_AUTO) {
    return IMAGE_SIZE_AUTO;
  }
  const match = normalized.match(/^(\d{2,5})\s*x\s*(\d{2,5})$/);
  if (!match) {
    throw new Error("图片尺寸格式应为 auto 或 宽x高");
  }
  const width = roundDownToMultiple(Number(match[1]));
  const height = roundDownToMultiple(Number(match[2]));
  if (width > MAX_IMAGE_SIZE || height > MAX_IMAGE_SIZE) {
    throw new Error(`图片尺寸不能超过 ${MAX_IMAGE_SIZE}x${MAX_IMAGE_SIZE}`);
  }
  return `${width}x${height}`;
}

export function parseRatio(value: string) {
  const match = String(value || "").trim().match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  if (!match) {
    throw new Error("比例格式应为 宽:高");
  }
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("比例必须大于 0");
  }
  return { width, height };
}

export function calculateImageSize(ratio: string) {
  const parsed = parseRatio(ratio);
  const ratioValue = parsed.width / parsed.height;
  const rawWidth = Math.sqrt(DEFAULT_AREA * ratioValue);
  const rawHeight = rawWidth / ratioValue;
  return normalizeImageSize(`${Math.round(rawWidth)}x${Math.round(rawHeight)}`);
}

export function formatImageSizeLabel(value: string) {
  const normalized = normalizeImageSize(value);
  return normalized === IMAGE_SIZE_AUTO ? "自动" : normalized;
}
