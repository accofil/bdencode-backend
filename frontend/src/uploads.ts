import type { ImageUploadProvider, UploadImageSet } from "./api/types";
import { t } from "./i18n";

// The labels are getters, so every read (including Object.entries) returns the
// text in the current interface language.
export const IMAGE_UPLOAD_PROVIDER_LABELS: Record<ImageUploadProvider, string> = {
  get auto() { return t("Automatikus: ImgBB → Catbox → Freeimage", "Automatic: ImgBB → Catbox → Freeimage"); },
  get imgbb() { return t("Csak ImgBB", "ImgBB only"); },
  get catbox() { return t("Csak Catbox", "Catbox only"); },
  get freeimage() { return t("Csak Freeimage", "Freeimage only"); },
};

export const UPLOAD_IMAGE_SET_LABELS: Record<UploadImageSet, string> = {
  get all() { return t("Minden kép: natív és SDR-nézet", "All images: native and SDR view"); },
  get sdr() { return t("Csak SDR-nézet (HDR-nél feleannyi kép)", "SDR view only (half the images for HDR)"); },
  get native() { return t("Csak natív kép (HDR-nél SDR-nézet nélkül)", "Native image only (no SDR view for HDR)"); },
};

export function imageUploadProviderLabel(provider: ImageUploadProvider): string {
  return IMAGE_UPLOAD_PROVIDER_LABELS[provider];
}

export function uploadImageSetLabel(set: UploadImageSet): string {
  return UPLOAD_IMAGE_SET_LABELS[set];
}

export const IMAGE_HOST_NAMES: Record<string, string> = {
  imgbb: "ImgBB",
  catbox: "Catbox",
  freeimage: "Freeimage",
};

export function uploadImageSet(value: unknown): UploadImageSet {
  return value === "sdr" || value === "native" ? value : "all";
}
