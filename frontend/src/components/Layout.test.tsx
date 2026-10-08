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
