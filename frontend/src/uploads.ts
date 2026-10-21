import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import type { ImageUploadProvider, UploadImageSet } from "./api/types";
import { t } from "./i18n";

export const IMAGE_HOST_NAMES: Record<string, string> = {
  imgbb: "ImgBB",
  catbox: "Catbox",
  freeimage: "Freeimage",
};

/** The automatic order while the operator has not chosen one on the System page. */
export const DEFAULT_IMAGE_HOST_ORDER: readonly string[] = ["imgbb", "catbox", "freeimage"];

function hostNames(order: readonly string[]): string[] {
  return order.map((host) => IMAGE_HOST_NAMES[host] ?? host);
}

/** "ImgBB, Catbox, majd Freeimage" / "ImgBB, Catbox, then Freeimage". */
export function imageHostOrderText(order: readonly string[] = DEFAULT_IMAGE_HOST_ORDER): string {
  const names = hostNames(order);
  if (names.length < 2) return names.join("");
  const head = names.slice(0, -1).join(", ");
  const last = names[names.length - 1];
  return t(`${head}, majd ${last}`, `${head}, then ${last}`);
}

/** The provider choices; the automatic one names the hosts in `order`. */
export function imageUploadProviderLabels(order: readonly string[] = DEFAULT_IMAGE_HOST_ORDER): Record<ImageUploadProvider, string> {
  const chain = hostNames(order).join(" → ");
  return {
    auto: t(`Automatikus: ${chain}`, `Automatic: ${chain}`),
    imgbb: t("Csak ImgBB", "ImgBB only"),
    catbox: t("Csak Catbox", "Catbox only"),
    freeimage: t("Csak Freeimage", "Freeimage only"),
  };
}

// The labels are getters, so every read (including Object.entries) returns the
// text in the current interface language.  The automatic label shows the
// default order; pages that know the saved order use imageUploadProviderLabels.
export const IMAGE_UPLOAD_PROVIDER_LABELS: Record<ImageUploadProvider, string> = {
  get auto() { return imageUploadProviderLabels().auto; },
  get imgbb() { return imageUploadProviderLabels().imgbb; },
  get catbox() { return imageUploadProviderLabels().catbox; },
  get freeimage() { return imageUploadProviderLabels().freeimage; },
};

export const UPLOAD_IMAGE_SET_LABELS: Record<UploadImageSet, string> = {
  get all() { return t("Minden kép: natív és SDR-nézet", "All images: native and SDR view"); },
  get sdr() { return t("Csak SDR-nézet (HDR-nél feleannyi kép)", "SDR view only (half the images for HDR)"); },
  get native() { return t("Csak natív kép (HDR-nél SDR-nézet nélkül)", "Native image only (no SDR view for HDR)"); },
};

export const IMAGE_UPLOAD_STATUS_QUERY_KEY = ["image-upload-status"] as const;

/**
 * The automatic host order saved on the System page.  Falls back to the
 * default order while it loads or when an older backend cannot tell it.
 */
export function useImageHostOrder(): readonly string[] {
  const status = useQuery({
    queryKey: IMAGE_UPLOAD_STATUS_QUERY_KEY,
    queryFn: api.imageUploadStatus,
    staleTime: 60_000,
    retry: false,
  });
  const order = status.data?.provider_order;
  return Array.isArray(order) && order.length > 0 ? order : DEFAULT_IMAGE_HOST_ORDER;
}

export function imageUploadProviderLabel(provider: ImageUploadProvider, order?: readonly string[]): string {
  return imageUploadProviderLabels(order)[provider];
}

export function uploadImageSetLabel(set: UploadImageSet): string {
  return UPLOAD_IMAGE_SET_LABELS[set];
}

export function uploadImageSet(value: unknown): UploadImageSet {
  return value === "sdr" || value === "native" ? value : "all";
}
