import { describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { IMAGE_UPLOAD_PROVIDER_LABELS, imageHostOrderText, imageUploadProviderLabels } from "./uploads";

describe("image host order labels", () => {
  it("names the default order while none is saved", () => {
    expect(IMAGE_UPLOAD_PROVIDER_LABELS.auto).toBe("Automatikus: ImgBB → Catbox → Freeimage");
    expect(imageHostOrderText()).toBe("ImgBB, Catbox, majd Freeimage");
  });

  it("follows the order saved on the System page", () => {
    const order = ["freeimage", "imgbb", "catbox"];
    expect(imageUploadProviderLabels(order).auto).toBe("Automatikus: Freeimage → ImgBB → Catbox");
    expect(imageUploadProviderLabels(order).catbox).toBe("Csak Catbox");
    setLanguage("en", { persist: false });
    expect(imageUploadProviderLabels(order).auto).toBe("Automatic: Freeimage → ImgBB → Catbox");
    expect(imageHostOrderText(order)).toBe("Freeimage, ImgBB, then Catbox");
  });
});
