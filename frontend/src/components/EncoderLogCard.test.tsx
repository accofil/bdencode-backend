import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { EncoderLog } from "../api/types";
import { makeJob } from "../test/fixtures";
import { renderApp } from "../test/render";
import { EncoderLogCard } from "./EncoderLogCard";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, encoderLog: vi.fn() } };
});

function log(overrides: Partial<EncoderLog> = {}): EncoderLog {
  return {
    available: true,
    encoder: "x264",
    finished: true,
    options: "cabac=1 ref=4 crf=17.5",
    summary: [
      "frame=139518 fps=8.2 q=-1.0 Lsize=14539218kB time=01:36:58.93 bitrate=20468.6kbits/s speed=0.343x",
      "[libx264 @ 0x1] frame I:822   Avg QP:14.68  size:297126",
      "[libx264 @ 0x1] kb/s:20466.49",
    ],
    text: "[libx264 @ 0x1] options: cabac=1\n[libx264 @ 0x1] kb/s:20466.49\n",
    line_count: 38,
    raw_bytes: 1570800,
    truncated: false,
    ...overrides,
  };
}

describe("EncoderLogCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the closing summary of a finished encode with download and copy", async () => {
    vi.mocked(api.encoderLog).mockResolvedValue(log());
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderApp(<EncoderLogCard job={makeJob({ state: "COMPLETED" })} />);

    expect(await screen.findByText(/Kódoló log · x264/)).toBeInTheDocument();
    expect(screen.getByText("kész")).toBeInTheDocument();
    expect(screen.getByLabelText("Záró összegzés")).toHaveTextContent("Avg QP:14.68");
    expect(screen.getByRole("link", { name: /Letöltés/ })).toHaveAttribute("href", expect.stringMatching(/\/jobs\/job-1\/encoder-log\.txt$/));
    expect(screen.getByText(/Teljes tisztított log \(38 sor/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Másolás/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("kb/s:20466.49")));
  });

  it("says the summary comes at the end while the encode is still running", async () => {
    vi.mocked(api.encoderLog).mockResolvedValue(log({ finished: false, summary: [] }));
    renderApp(<EncoderLogCard job={makeJob({ state: "ENCODING" })} />);

    expect(await screen.findByText("fut")).toBeInTheDocument();
    expect(screen.getByText("A záró összegzés a kódolás végén jelenik meg.")).toBeInTheDocument();
  });

  it("stays out of the way before the encode and when there is no log", async () => {
    vi.mocked(api.encoderLog).mockResolvedValue({ available: false });
    const { container, unmount } = renderApp(<EncoderLogCard job={makeJob({ state: "READY" })} />);
    expect(api.encoderLog).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
    unmount();

    const second = renderApp(<EncoderLogCard job={makeJob({ state: "COMPLETED" })} />);
    await waitFor(() => expect(api.encoderLog).toHaveBeenCalled());
    expect(second.container).toBeEmptyDOMElement();
  });
});
