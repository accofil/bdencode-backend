import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { CapabilitiesResponse, HealthResponse } from "../api/types";
import { renderApp } from "../test/render";
import { Layout } from "./Layout";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      health: vi.fn(),
      capabilities: vi.fn(),
      cpuPolicy: vi.fn(),
    },
  };
});

const health = {
  status: "ok",
  active_job_id: null,
  queued_jobs: 0,
} as unknown as HealthResponse;

function capabilities(version: string): CapabilitiesResponse {
  return { api_version: "1", backend_version: version } as unknown as CapabilitiesResponse;
}

describe("Layout version", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.health).mockResolvedValue(health);
    vi.mocked(api.cpuPolicy).mockRejectedValue(new Error("no policy in this test"));
  });

  it("shows the server's version under the brand", async () => {
    vi.mocked(api.capabilities).mockResolvedValue(capabilities(__APP_VERSION__));

    renderApp(<Layout />);

    expect(await screen.findByText(`v${__APP_VERSION__}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Oldal frissítése/ })).not.toBeInTheDocument();
  });

  it("asks for a reload when this tab runs another version than the server", async () => {
    vi.mocked(api.capabilities).mockResolvedValue(capabilities("99.0.0"));

    renderApp(<Layout />);

    expect(await screen.findByText("v99.0.0")).toBeInTheDocument();
    expect(
      screen.getByText(`Ez a lap a v${__APP_VERSION__} felületét futtatja, a szerveren a v99.0.0 van.`),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Oldal frissítése/ })).toBeInTheDocument();
  });
});

describe("Layout host warnings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.capabilities).mockResolvedValue(capabilities(__APP_VERSION__));
    vi.mocked(api.cpuPolicy).mockRejectedValue(new Error("no policy in this test"));
  });

  it("says so when jobs wait and the worker service is not running", async () => {
    vi.mocked(api.health).mockResolvedValue({ ...health, queued_jobs: 1, worker_active: false } as HealthResponse);

    renderApp(<Layout />);

    expect(await screen.findByText("A worker szolgáltatás nem fut")).toBeInTheDocument();
    expect(screen.getByText(/1 munka vár, de senki nem veszi fel/)).toBeInTheDocument();
    expect(screen.getByText(/sudo systemctl start bdencode-worker/)).toBeInTheDocument();
  });

  it("stays quiet about a stopped worker when nothing waits, or when systemd cannot tell", async () => {
    vi.mocked(api.health).mockResolvedValue({ ...health, queued_jobs: 0, worker_active: false } as HealthResponse);
    const { unmount } = renderApp(<Layout />);
    await screen.findByText(`v${__APP_VERSION__}`);
    expect(screen.queryByText("A worker szolgáltatás nem fut")).not.toBeInTheDocument();
    unmount();

    vi.mocked(api.health).mockResolvedValue({ ...health, queued_jobs: 2, worker_active: null } as HealthResponse);
    renderApp(<Layout />);
    await screen.findByText(`v${__APP_VERSION__}`);
    expect(screen.queryByText("A worker szolgáltatás nem fut")).not.toBeInTheDocument();
  });

  it("warns about little free disk space and escalates when it is almost full", async () => {
    const GIB = 1024 ** 3;
    vi.mocked(api.health).mockResolvedValue({ ...health, disk_free_bytes: 80 * GIB, disk_total_bytes: 1000 * GIB } as HealthResponse);
    const { unmount } = renderApp(<Layout />);
    expect(await screen.findByText("Kevés a szabad lemezhely")).toBeInTheDocument();
    expect(screen.getByText(/Szabad hely: 80 GiB/)).toBeInTheDocument();
    unmount();

    vi.mocked(api.health).mockResolvedValue({ ...health, disk_free_bytes: 5 * GIB, disk_total_bytes: 1000 * GIB } as HealthResponse);
    renderApp(<Layout />);
    expect(await screen.findByText("Majdnem megtelt a lemez")).toBeInTheDocument();
  });

  it("shows nothing for a healthy host", async () => {
    const GIB = 1024 ** 3;
    vi.mocked(api.health).mockResolvedValue({ ...health, queued_jobs: 1, worker_active: true, disk_free_bytes: 500 * GIB } as HealthResponse);
    renderApp(<Layout />);
    await screen.findByText(`v${__APP_VERSION__}`);
    expect(screen.queryByText("A worker szolgáltatás nem fut")).not.toBeInTheDocument();
    expect(screen.queryByText("Kevés a szabad lemezhely")).not.toBeInTheDocument();
  });
});
