export const IMAGE_SIZE_AUTO = "auto";

const MIN_IMAGE_SIZE = 16;
const MAX_IMAGE_SIZE = 4096;
const DEFAULT_AREA = 1024 * 1024;

export type ImageSizeMode = "auto" | "ratio" | "custom";
export type ImageResolutionPreset = "1k" | "2k" | "4k";
export type ImageAspectRatioPreset = "auto" | "1:1" | "3:4" | "4:3" | "9:16" | "16:9";

export type ImageGenerationPreference = {
  resolution: ImageResolutionPreset;
  ratio: ImageAspectRatioPreset;
};

export type ImageSizeSelection = {
  mode: ImageSizeMode;
  value: string;
  ratio?: string;
  width?: number;
  height?: number;
};

export const IMAGE_RESOLUTION_PRESETS: Array<{
  value: ImageResolutionPreset;
  label: string;
  edge: number;
}> = [
  { value: "1k", label: "1K", edge: 1024 },
  { value: "2k", label: "2K", edge: 2048 },
  { value: "4k", label: "4K", edge: 4096 },
];

export const IMAGE_ASPECT_RATIO_PRESETS: Array<{
  value: ImageAspectRatioPreset;
  label: string;
}> = [
  { value: "auto", label: "AUTO" },
  { value: "1:1", label: "1:1" },
  { value: "3:4", label: "3:4" },
  { value: "4:3", label: "4:3" },
  { value: "9:16", label: "9:16" },
  { value: "16:9", label: "16:9" },
];

export const DEFAULT_IMAGE_GENERATION_PREFERENCE: ImageGenerationPreference = {
  resolution: "1k",
  ratio: "auto",
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

export function normalizeImageGenerationPreference(
  value: Partial<ImageGenerationPreference> | null | undefined,
): ImageGenerationPreference {
  const candidate = value || {};
  const resolution =
    IMAGE_RESOLUTION_PRESETS.find((item) => item.value === candidate.resolution)?.value ||
    DEFAULT_IMAGE_GENERATION_PREFERENCE.resolution;
  const ratio =
    IMAGE_ASPECT_RATIO_PRESETS.find((item) => item.value === candidate.ratio)?.value ||
    DEFAULT_IMAGE_GENERATION_PREFERENCE.ratio;
  return { resolution, ratio };
}

export function calculateImageSizeFromPreference(
  preference: ImageGenerationPreference,
) {
  const normalized = normalizeImageGenerationPreference(preference);
  if (normalized.ratio === "auto") {
    return IMAGE_SIZE_AUTO;
  }
  const preset = IMAGE_RESOLUTION_PRESETS.find(
    (item) => item.value === normalized.resolution,
  );
  const edge = preset?.edge || IMAGE_RESOLUTION_PRESETS[0].edge;
  const ratio = parseRatio(normalized.ratio);
  const landscape = ratio.width >= ratio.height;
  const width = landscape ? edge : Math.round((edge * ratio.width) / ratio.height);
  const height = landscape ? Math.round((edge * ratio.height) / ratio.width) : edge;
  return normalizeImageSize(`${width}x${height}`);
}

export function formatImagePreferenceLabel(
  preference: ImageGenerationPreference,
) {
  const normalized = normalizeImageGenerationPreference(preference);
  const resolutionLabel =
    IMAGE_RESOLUTION_PRESETS.find((item) => item.value === normalized.resolution)?.label ||
    "1K";
  const ratioLabel =
    IMAGE_ASPECT_RATIO_PRESETS.find((item) => item.value === normalized.ratio)?.label ||
    "AUTO";
  const size = calculateImageSizeFromPreference(normalized);
  return size === IMAGE_SIZE_AUTO
    ? `${resolutionLabel} · ${ratioLabel}`
    : `${resolutionLabel} · ${ratioLabel} · ${size}`;
}
