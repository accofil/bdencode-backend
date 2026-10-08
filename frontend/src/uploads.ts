import type { ImageUploadProvider, UploadImageSet } from "./api/types";

export const IMAGE_UPLOAD_PROVIDER_LABELS: Record<ImageUploadProvider, string> = {
  auto: "Automatikus: ImgBB → Catbox → Freeimage",
  imgbb: "Csak ImgBB",
  catbox: "Csak Catbox",
  freeimage: "Csak Freeimage",
};

export const UPLOAD_IMAGE_SET_LABELS: Record<UploadImageSet, string> = {
  all: "Minden kép: natív és SDR-nézet",
  sdr: "Csak SDR-nézet (HDR-nél feleannyi kép)",
  native: "Csak natív kép (HDR-nél SDR-nézet nélkül)",
};

export const IMAGE_HOST_NAMES: Record<string, string> = {
  imgbb: "ImgBB",
  catbox: "Catbox",
  freeimage: "Freeimage",
};

export function uploadImageSet(value: unknown): UploadImageSet {
  return value === "sdr" || value === "native" ? value : "all";
}
