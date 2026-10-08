import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { CpuPolicyView } from "../api/types";
import { renderApp } from "../test/render";
import { cpuShareInForce, CpuPolicyPanel } from "./CpuPolicyPanel";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, cpuPolicy: vi.fn(), saveCpuPolicy: vi.fn() } };
});

function view(overrides: Partial<CpuPolicyView> = {}): CpuPolicyView {
  return {
    policy: { schema_version: 1, day_percent: 80, night: { enabled: false, percent: 100, start: "23:00", end: "07:00" }, timezone: null },
    saved: false,
    expected: { percent: 80, mode: "day" },
    applied: null,
    install_default_percent: 80,
    logical_cpus: 24,
    limits: { min_percent: 10, max_percent: 100 },
    ...overrides,
  };
}

describe("CPU policy", () => {
  beforeEach(() => vi.clearAllMocks());

  it("trusts only what the helper applied, else the installed default", () => {
    expect(cpuShareInForce(view())).toEqual({ percent: 80, mode: "day" });
    expect(cpuShareInForce(view({ saved: true, expected: { percent: 100, mode: "night" } }))).toEqual({ percent: 80, mode: "day" });
    expect(cpuShareInForce(view({ applied: { state: "applied", percent: 100, mode: "night" } }))).toEqual({ percent: 100, mode: "night" });
    expect(cpuShareInForce(undefined)).toBeNull();
  });

  it("saves a lower day share and a full night window with the browser's zone", async () => {
    const user = userEvent.setup();
    vi.mocked(api.cpuPolicy).mockResolvedValue(view({ applied: { state: "applied", percent: 80, mode: "day", applied_at: "2026-10-04T16:00:00Z" } }));
    vi.mocked(api.saveCpuPolicy).mockImplementation(async (policy) => view({ policy, saved: true }));
    renderApp(<CpuPolicyPanel />);

    expect(await screen.findByText("Most: 80% · nappali")).toBeInTheDocument();
    expect(screen.getByText("≈ 19.2 logikai CPU")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Mentés" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByRole("slider", { name: "Nappali CPU-keret" }), { target: { value: "60" } });
    await user.click(screen.getByRole("checkbox", { name: /Éjszakai mód/ }));
    fireEvent.change(screen.getByLabelText("Éjszakai mód kezdete"), { target: { value: "22:30" } });
    expect(screen.getByText("≈ 14.4 logikai CPU")).toBeInTheDocument();
    await user.click(save);

    await waitFor(() => expect(api.saveCpuPolicy).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(api.saveCpuPolicy).mock.calls[0][0];
    expect(sent).toMatchObject({
      schema_version: 1,
      day_percent: 60,
      night: { enabled: true, percent: 100, start: "22:30", end: "07:00" },
    });
    expect(typeof sent.timezone === "string" || sent.timezone === null).toBe(true);
  });

  it("explains a policy the helper has not applied yet or rejected", async () => {
    vi.mocked(api.cpuPolicy).mockResolvedValue(view({ saved: true }));
    const first = renderApp(<CpuPolicyPanel />);
    expect(await screen.findByText("Az alkalmazó még nem futott")).toBeInTheDocument();
    expect(screen.getByText("A telepítéskori 80%-os keret van érvényben.")).toBeInTheDocument();
    first.unmount();

    vi.mocked(api.cpuPolicy).mockResolvedValue(view({ saved: true, applied: { state: "failed", message: "systemctl set-property failed" } }));
    renderApp(<CpuPolicyPanel />);
    expect(await screen.findByText("A keret beállítása nem sikerült")).toBeInTheDocument();
    expect(screen.getByText("systemctl set-property failed")).toBeInTheDocument();
  });
});
