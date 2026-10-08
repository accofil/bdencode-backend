import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { AIRecommendationStatus, CapabilitiesResponse, RuntimeCapabilitiesResponse } from "../api/types";
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

function mockRuntime(runtime: RuntimeCapabilitiesResponse) {
  vi.mocked(api.aiRecommendationStatus).mockResolvedValue(aiStatus());
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
});
