import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { setLanguage } from "../i18n";
import type { AIRecommendationStatus, CapabilitiesResponse, ImageUploadStatus, RuntimeCapabilitiesResponse } from "../api/types";
import { renderApp } from "../test/render";
import { SystemPage } from "./SystemPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      health: vi.fn(),
      runtimeCapabilities: vi.fn(),
      capabilities: vi.fn(),
      cpuPolicy: vi.fn(),
      aiRecommendationStatus: vi.fn(),
      saveAISettings: vi.fn(),
      setAIKey: vi.fn(),
      deleteAIKey: vi.fn(),
      imageUploadStatus: vi.fn(),
      saveImageUploadSettings: vi.fn(),
      setImageUploadKey: vi.fn(),
      deleteImageUploadKey: vi.fn(),
    },
  };
});

const capabilities = {
  api_version: "1",
  backend_version: "2.0.0",
  constraints: { cpu_budget_fraction: 0.8 },
} as CapabilitiesResponse;

function aiStatus(overrides: Partial<AIRecommendationStatus> = {}): AIRecommendationStatus {
  return {
    provider: "openai",
    configured: false,
    model: "gpt-5.6-terra",
    default_provider: null,
    providers: [
      { id: "openai", label: "OpenAI", credential: "openai-api-key", configured: false, model: "gpt-5.6-terra", default_model: "gpt-5.6-terra" },
      { id: "anthropic", label: "Claude (Anthropic)", credential: "anthropic-api-key", configured: false, model: "claude-opus-5-5", default_model: "claude-opus-5-5" },
    ],
    key_management: { available: true, results: [] },
    structured_output: true,
    requires_operator_confirmation: true,
    ...overrides,
  };
}

function uploadStatus(overrides: Partial<ImageUploadStatus> = {}): ImageUploadStatus {
  return {
    provider_order: ["imgbb", "catbox", "freeimage"],
    default_order: ["imgbb", "catbox", "freeimage"],
    custom_order: false,
    hosts: [
      { id: "imgbb", label: "ImgBB", credential: "imgbb-api-key", key_required: true, configured: false },
      { id: "catbox", label: "Catbox", credential: "catbox-userhash", key_required: false, configured: false },
      { id: "freeimage", label: "Freeimage", credential: "freeimage-api-key", key_required: true, configured: false },
    ],
    key_management: { available: true, results: [] },
    ...overrides,
  };
}

function mockRuntime(runtime: RuntimeCapabilitiesResponse) {
  vi.mocked(api.aiRecommendationStatus).mockResolvedValue(aiStatus());
  vi.mocked(api.imageUploadStatus).mockResolvedValue(uploadStatus());
  vi.mocked(api.health).mockResolvedValue({
    status: "ok",
    database: "/home/encoder/encode/state/encoder.sqlite3",
    schema_version: 7,
    active_job_id: null,
    blocking_state: null,
    queued_jobs: 0,
  });
  vi.mocked(api.capabilities).mockResolvedValue(capabilities);
  vi.mocked(api.runtimeCapabilities).mockResolvedValue(runtime);
  const installed = runtime.worker_cpu_policy?.requested_percent ?? 80;
  vi.mocked(api.cpuPolicy).mockResolvedValue({
    policy: { schema_version: 1, day_percent: installed, night: { enabled: false, percent: 100, start: "23:00", end: "07:00" } },
    saved: false,
    expected: { percent: installed, mode: "day" },
    applied: null,
    install_default_percent: installed,
    logical_cpus: 16,
    limits: { min_percent: 10, max_percent: 100 },
  });
}

describe("SystemPage runtime capabilities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders omitted doctor fields as unknown instead of failures or zero-byte storage", async () => {
    mockRuntime({
      host: { logical_cpus: 16 },
      tools: {
        vspipe: {
          path: "/home/encoder/encode/app/tools/current/bin/vspipe",
          version: "VapourSynth Video Processing Library",
          available: true,
        },
      },
      ffmpeg: { encoders: ["libx264", "libx265", "flac"] },
    });

    renderApp(<SystemPage />, "/settings");

    const vapourSynth = await screen.findByText("VapourSynth Ismeretlen");
    expect(vapourSynth).toHaveClass("badge--neutral");
    expect(screen.queryByText("VapourSynth hiba")).not.toBeInTheDocument();
    expect(screen.getByText("Tárhelyadatok: Ismeretlen")).toBeInTheDocument();
    expect(screen.queryByText(/0 B/)).not.toBeInTheDocument();
    expect(screen.getByText("Útvonal").nextElementSibling).toHaveTextContent("Ismeretlen");
    expect(screen.getByText("Olvasható").nextElementSibling).toHaveTextContent("Ismeretlen");
    expect(screen.getByText("Írható").nextElementSibling).toHaveTextContent("Ismeretlen");
  });

  it("keeps the loaded data and says it is reconnecting when the API answers nothing for a moment", async () => {
    mockRuntime({ host: { logical_cpus: 16 }, tools: { vspipe: { path: "/tools/vspipe", version: "VapourSynth", available: true } }, ffmpeg: { encoders: ["libx264"] } });
    renderApp(<SystemPage />, "/settings");
    await screen.findByText("VapourSynth Ismeretlen");

    // The API restarts (a saved key): the next refresh fails.
    vi.mocked(api.runtimeCapabilities).mockRejectedValue(new Error("Failed to fetch"));
    fireEvent.click(screen.getByRole("button", { name: "Frissítés" }));

    expect(await screen.findByText("Újracsatlakozás…")).toBeInTheDocument();
    expect(screen.getByText("VapourSynth Ismeretlen")).toBeInTheDocument();
    expect(screen.queryByText("A rendszerállapot nem olvasható")).not.toBeInTheDocument();
  });

  it("renders the path, VapourSynth result, warnings and storage values from a full doctor report", async () => {
    mockRuntime({
      status: "ok",
      database: {
        path: "/home/encoder/encode/state/encoder.sqlite3",
        schema_version: 7,
        active_job: null,
      },
      paths: {
        data: {
          path: "/home/encoder/encode",
          exists: true,
          readable: true,
          writable: true,
          free_bytes: 2 * 1024 ** 3,
          total_bytes: 8 * 1024 ** 3,
          ok: true,
        },
        sources: [{ path: "/storage", exists: true, readable: true, writable: false, ok: true }],
      },
      host: { logical_cpus: 16 },
      tools: {
        vspipe: {
          path: "/home/encoder/encode/app/tools/current/bin/vspipe",
          version: "VapourSynth Video Processing Library",
          available: true,
        },
      },
      ffmpeg: { encoders: ["libx264", "libx265", "flac"], filters: [], protocols: ["bluray"] },
      missing_ffmpeg_capabilities: { encoders: [], filters: [], protocols: [] },
      vapoursynth: {
        ok: true,
        plugins: { bs: true, bwdif: true, vivtc: true, resize: true },
        error: null,
      },
      imgbb_credential: { configured: true, encrypted_at_rest: true, permissions: "0600", permissions_ok: true },
      worker_cpu_policy: { requested_percent: 75, logical_cpus: 16, systemd_cpu_quota_percent: 1200 },
      warnings: ["Teszt figyelmeztetés"],
    });

    renderApp(<SystemPage />, "/settings");

    const vapourSynth = await screen.findByText("VapourSynth OK");
    expect(vapourSynth).toHaveClass("badge--success");
    expect(screen.getAllByText("/home/encoder/encode")).toHaveLength(2);
    expect(screen.getByText("2.00 GiB szabad")).toBeInTheDocument();
    expect(screen.getByText("6.00 GiB használatban · 8.00 GiB összesen")).toBeInTheDocument();
    expect(screen.getByText("Olvasható").nextElementSibling).toHaveTextContent("Igen");
    expect(screen.getByText("Írható").nextElementSibling).toHaveTextContent("Igen");
    expect(screen.getByText("75% teljes keret")).toBeInTheDocument();
    expect(screen.getByText("Teszt figyelmeztetés")).toBeInTheDocument();
  });

  it("keeps explicit runtime failures visible", async () => {
    mockRuntime({
      paths: {
        data: {
          path: "/home/encoder/encode",
          exists: true,
          readable: false,
          writable: false,
          free_bytes: 1024,
          total_bytes: 4096,
          ok: false,
        },
      },
      vapoursynth: { ok: false, plugins: {}, error: "plugin import failed" },
    });

    renderApp(<SystemPage />, "/settings");

    const vapourSynth = await screen.findByText("VapourSynth hiba");
    expect(vapourSynth).toHaveClass("badge--danger");
    expect(screen.getByText("Olvasható").nextElementSibling).toHaveTextContent("Nem");
    expect(screen.getByText("Írható").nextElementSibling).toHaveTextContent("Nem");
  });

  it("lets the operator enter an AI key and waits for the helper to store it", async () => {
    mockRuntime({});
    vi.mocked(api.setAIKey).mockResolvedValue({ request_id: "r1", provider: "anthropic", action: "set" });

    renderApp(<SystemPage />, "/settings");

    const key = await screen.findByLabelText("Claude (Anthropic) API-kulcs");
    expect(screen.getByText("Nincs beállítva")).toBeInTheDocument();
    expect(key).toHaveAttribute("type", "password");
    fireEvent.change(key, { target: { value: "sk-ant-api03-secret" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Kulcs mentése" })[1]);

    await waitFor(() => expect(api.setAIKey).toHaveBeenCalledWith("anthropic", "sk-ant-api03-secret"));
    expect(await screen.findByText("Kulcs mentése folyamatban")).toBeInTheDocument();
    expect(key).toHaveValue("");

    vi.mocked(api.aiRecommendationStatus).mockResolvedValue(aiStatus({
      provider: "anthropic",
      configured: true,
      model: "claude-opus-5-5",
      providers: aiStatus().providers!.map((item) => item.id === "anthropic" ? { ...item, configured: true } : item),
      key_management: { available: true, results: [{ request_id: "r1", state: "applied", credential: "anthropic-api-key" }] },
    }));
    expect(await screen.findByText(/kulcsa elmentve/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("Használatra kész · Claude (Anthropic)")).toBeInTheDocument();
  });

  it("saves the default provider and a model override", async () => {
    mockRuntime({});
    vi.mocked(api.saveAISettings).mockResolvedValue(aiStatus({ default_provider: "anthropic", provider: "anthropic" }));

    renderApp(<SystemPage />, "/settings");

    fireEvent.change(await screen.findByLabelText("Alapértelmezett szolgáltató"), { target: { value: "anthropic" } });
    fireEvent.change(screen.getAllByLabelText("Modell")[1], { target: { value: "claude-sonnet-5-5" } });
    fireEvent.click(screen.getByRole("button", { name: "Szolgáltató és modellek mentése" }));

    await waitFor(() => expect(api.saveAISettings).toHaveBeenCalledWith({
      default_provider: "anthropic",
      openai_model: null,
      anthropic_model: "claude-sonnet-5-5",
    }));
  });

  it("tells whether the crop scan has a GPU or runs on the CPU", async () => {
    mockRuntime({ worker_gpu: { devices: [], crop_hwaccel: "auto", crop_decode: "cpu" } });
    const first = renderApp(<SystemPage />, "/settings");
    expect(await first.findByText("Nincs GPU: a crop-keresés CPU-n fut")).toBeInTheDocument();
    first.unmount();

    mockRuntime({ worker_gpu: { devices: ["/dev/dxg"], crop_hwaccel: "auto", crop_decode: "gpu_if_available" } });
    renderApp(<SystemPage />, "/settings");
    expect(await screen.findByText("GPU a crop-kereséshez (/dev/dxg)")).toBeInTheDocument();
  });

  it("explains when the server cannot take keys from the page", async () => {
    mockRuntime({});
    vi.mocked(api.aiRecommendationStatus).mockResolvedValue(aiStatus({ key_management: { available: false, results: [] } }));

    renderApp(<SystemPage />, "/settings");

    expect(await screen.findByText("A kulcs itt nem állítható be")).toBeInTheDocument();
    expect(screen.queryByLabelText("OpenAI API-kulcs")).not.toBeInTheDocument();
  });

  it("shows worker credential readiness instead of the API process runtime view", async () => {
    mockRuntime({
      image_upload_credentials: {
        imgbb: {
          configured: true,
          runtime_loaded: null,
          consumer_service: "bdencode-worker.service",
          service_bound: true,
          service_active: true,
          ready_for_consumer: true,
        },
        catbox: {
          configured: true,
          runtime_loaded: null,
          consumer_service: "bdencode-worker.service",
          service_bound: true,
          service_active: false,
          ready_for_consumer: true,
        },
        freeimage: {
          configured: true,
          runtime_loaded: null,
          consumer_service: "bdencode-worker.service",
          service_bound: false,
          service_active: true,
          ready_for_consumer: false,
        },
      },
    });

    renderApp(<SystemPage />, "/settings");

    expect(await screen.findByText("Használatra kész")).toBeInTheDocument();
    expect(screen.getByText("Bekötve, a worker áll")).toBeInTheDocument();
    expect(screen.getByText("Nincs a workerhez kötve")).toBeInTheDocument();
    expect(screen.getAllByText("bdencode-worker.service")).toHaveLength(3);
  });

  it("sets an image host key only in a valid format and never shows it back", async () => {
    mockRuntime({});
    const imgbbKey = "0123456789abcdef0123456789abcdef";
    vi.mocked(api.setImageUploadKey).mockResolvedValue({ request_id: "u1", host: "imgbb", action: "set" });

    renderApp(<SystemPage />, "/settings");

    const key = await screen.findByLabelText("ImgBB API-kulcs");
    expect(key).toHaveAttribute("type", "password");
    expect(screen.getByText("0 / 3 kulcs beállítva")).toBeInTheDocument();
    expect(screen.getByText("Névtelen feltöltés")).toBeInTheDocument();

    fireEvent.change(key, { target: { value: "too short" } });
    fireEvent.click(screen.getByRole("button", { name: "ImgBB kulcs mentése" }));
    expect(await screen.findByText("A(z) ImgBB API-kulcsa pontosan 32 karakter, csak betű és szám.")).toBeInTheDocument();
    expect(api.setImageUploadKey).not.toHaveBeenCalled();

    fireEvent.change(key, { target: { value: ` ${imgbbKey}\n` } });
    fireEvent.click(screen.getByRole("button", { name: "ImgBB kulcs mentése" }));
    await waitFor(() => expect(api.setImageUploadKey).toHaveBeenCalledWith("imgbb", imgbbKey));
    expect(await screen.findByText("A képfeltöltő kulcsának mentése…")).toBeInTheDocument();
    expect(key).toHaveValue("");

    vi.mocked(api.imageUploadStatus).mockResolvedValue(uploadStatus({
      hosts: uploadStatus().hosts.map((item) => item.id === "imgbb" ? { ...item, configured: true } : item),
      key_management: { available: true, results: [{ request_id: "u1", state: "applied", credential: "imgbb-api-key" }] },
    }));
    expect(await screen.findByText(/kulcsa elmentve; a worker a következő feltöltésnél/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("1 / 3 kulcs beállítva")).toBeInTheDocument();
    expect(screen.getByLabelText("ImgBB API-kulcs")).toHaveValue("");
    expect(screen.getByText("Új API-kulcs (csere)")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(imgbbKey);
    expect(screen.getByRole("button", { name: "ImgBB kulcs törlése" })).toBeInTheDocument();
  });

  it("deletes an image host key and reports a key the helper refused", async () => {
    mockRuntime({});
    vi.mocked(api.imageUploadStatus).mockResolvedValue(uploadStatus({
      hosts: uploadStatus().hosts.map((item) => item.id === "freeimage" ? { ...item, configured: true } : item),
    }));
    vi.mocked(api.deleteImageUploadKey).mockResolvedValue({ request_id: "d1", host: "freeimage", action: "delete" });

    renderApp(<SystemPage />, "/settings");

    fireEvent.click(await screen.findByRole("button", { name: "Freeimage kulcs törlése" }));
    await waitFor(() => expect(api.deleteImageUploadKey).toHaveBeenCalledWith("freeimage"));
    vi.mocked(api.imageUploadStatus).mockResolvedValue(uploadStatus({
      hosts: uploadStatus().hosts.map((item) => item.id === "freeimage" ? { ...item, configured: true } : item),
      key_management: { available: true, results: [{ request_id: "d1", state: "rejected", message: "this credential cannot be changed from the web UI" }] },
    }));
    expect(await screen.findByText(/A kulcsot a szerver nem mentette el: this credential/, {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("saves the automatic host order", async () => {
    mockRuntime({});
    vi.mocked(api.saveImageUploadSettings).mockResolvedValue(uploadStatus({ provider_order: ["freeimage", "imgbb", "catbox"], custom_order: true }));

    renderApp(<SystemPage />, "/settings");

    expect(await screen.findByText(/Most: ImgBB, Catbox, majd Freeimage\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sorrend mentése" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "ImgBB előrébb" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Freeimage előrébb" }));
    fireEvent.click(screen.getByRole("button", { name: "Freeimage előrébb" }));
    expect(screen.getByText(/Most: Freeimage, ImgBB, majd Catbox\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sorrend mentése" }));

    await waitFor(() => expect(api.saveImageUploadSettings).toHaveBeenCalledWith({ provider_order: ["freeimage", "imgbb", "catbox"] }));
    fireEvent.click(await screen.findByRole("button", { name: "Alapértelmezett sorrend" }));
    await waitFor(() => expect(api.saveImageUploadSettings).toHaveBeenLastCalledWith({ provider_order: null }));
  });

  it("shows information in grey apart from the warnings, and the warning heading only for real warnings", async () => {
    const vmaf = "FFmpeg libvmaf filter missing; the official standalone VMAF CLI will be used";
    mockRuntime({ warnings: [], notices: [{ severity: "info", message: vmaf }] });
    const first = renderApp(<SystemPage />, "/settings");

    const information = await first.findByText("Tájékoztatás");
    expect(information.closest(".notice")).toHaveClass("notice--muted");
    expect(information.closest(".notice")).toHaveTextContent(vmaf);
    expect(first.queryByText("Runtime figyelmeztetések")).not.toBeInTheDocument();
    first.unmount();

    mockRuntime({
      warnings: ["ImgBB upload credential is not configured"],
      notices: [
        { severity: "warning", message: "ImgBB upload credential is not configured" },
        { severity: "info", message: vmaf },
      ],
    });
    renderApp(<SystemPage />, "/settings");
    const warnings = await screen.findByText("Runtime figyelmeztetések");
    expect(warnings.closest(".notice")).toHaveClass("notice--warning");
    expect(warnings.closest(".notice")).toHaveTextContent("ImgBB upload credential is not configured");
    expect(warnings.closest(".notice")).not.toHaveTextContent(vmaf);
    expect(screen.getByText("Tájékoztatás").closest(".notice")).not.toHaveTextContent("ImgBB upload credential");
  });

  it("explains when the server cannot take image host keys from the page", async () => {
    mockRuntime({});
    vi.mocked(api.imageUploadStatus).mockResolvedValue(uploadStatus({ key_management: { available: false, results: [] } }));

    renderApp(<SystemPage />, "/settings");

    expect(await screen.findByText("A képfeltöltők kulcsa itt nem állítható be")).toBeInTheDocument();
    expect(screen.queryByLabelText("ImgBB API-kulcs")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Freeimage hátrébb" })).toBeDisabled();
  });

  it("renders the System page in English", async () => {
    setLanguage("en", { persist: false });
    mockRuntime({
      paths: {
        data: {
          path: "/home/encoder/encode",
          exists: true,
          readable: true,
          writable: true,
          free_bytes: 2 * 1024 ** 3,
          total_bytes: 8 * 1024 ** 3,
          ok: true,
        },
        sources: [],
      },
      host: { logical_cpus: 16 },
      tools: { vspipe: { path: "/usr/bin/vspipe", version: "R70", available: true } },
      image_upload_credentials: {
        imgbb: {
          configured: true,
          runtime_loaded: null,
          consumer_service: "bdencode-worker.service",
          service_bound: true,
          service_active: true,
          ready_for_consumer: true,
        },
      },
      worker_cpu_policy: { requested_percent: 75, logical_cpus: 16, systemd_cpu_quota_percent: 1200 },
    });

    renderApp(<SystemPage />, "/settings");

    expect(await screen.findByRole("heading", { name: "Installed programs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Server and capabilities" })).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getByText("Processor")).toBeInTheDocument();
    expect(screen.getAllByText("Storage").length).toBeGreaterThan(0);
    expect(screen.getByText("2.00 GiB free")).toBeInTheDocument();
    expect(screen.getByText("Ready to use")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "CPU share" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "AI adviser" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Save key" })).toHaveLength(2);
    expect(await screen.findByRole("heading", { name: "Image upload" })).toBeInTheDocument();
    expect(screen.getByLabelText("Catbox userhash")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "Save the ImgBB key" })).toBeInTheDocument();
    expect(screen.getByText(/Now: ImgBB, Catbox, then Freeimage\./)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Release check and update" })).toBeInTheDocument();
    expect(screen.getByText("Readable").nextElementSibling).toHaveTextContent("Yes");
    expect(screen.queryByText("Telepített programok")).not.toBeInTheDocument();
  });
});
