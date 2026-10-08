import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DiscScanResult, SelectionValidation } from "../api/types";
import { api, ApiError } from "../api/client";
import { setLanguage } from "../i18n";
import { makeJob, makeScan } from "../test/fixtures";
import { renderApp } from "../test/render";
import { SelectionWizard } from "./SelectionWizard";

function makeScanWithRetainedSubtitle(): DiscScanResult {
  const scan = makeScan();
  scan.playlists[0].streams.push({
    id: "subtitle:4608",
    index: 2,
    pid: 4608,
    kind: "subtitle",
    codec: "hdmv_pgs_subtitle",
    codec_profile: null,
    language: {
      iso639_2t: "hun",
      bcp47: "hu",
      confidence: 1,
      needs_review: false,
    },
    title: "Magyar",
    channels: null,
    channel_layout: null,
    sample_rate: null,
    bit_depth: null,
    default: true,
    forced: false,
    roles: [],
    object_audio: false,
    video: null,
  });
  return scan;
}

function makeScanWithTrueHdAndHungarianDub(): DiscScanResult {
  const scan = makeScan();
  const [video, english] = scan.playlists[0].streams;
  scan.playlists[0].streams = [
    video,
    { ...english, id: "audio:4352", codec: "truehd", codec_profile: "Dolby TrueHD + Dolby Atmos", channels: 8, channel_layout: "7.1", object_audio: true, roles: ["main"], title: "English Atmos" },
    { ...english, id: "audio:4353", index: 2, pid: 4353, codec: "ac3", channels: 6, default: false, roles: ["dub"], title: "Magyar", language: { iso639_2t: "hun", bcp47: "hu", confidence: 1, needs_review: false } },
  ];
  return scan;
}

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      profileSchema: vi.fn(),
      aitherPresets: vi.fn(),
      profileRecommendation: vi.fn(),
      aiRecommendationStatus: vi.fn(),
      aiRecommendation: vi.fn(),
      validateSelection: vi.fn(),
      saveSelection: vi.fn(),
      noiseProfiles: vi.fn(),
      profileLibrary: vi.fn(),
    },
  };
});

describe("SelectionWizard", () => {
  const validation: SelectionValidation = {
    valid: true,
    playlist_id: "00001",
    encoder: "x264",
    settings: { crf: 18, preset: "slow", profile: "high" },
    ffmpeg_video_args: ["--crf", "18"],
    crop: { left: 0, top: 0, right: 0, bottom: 0 },
    temporal_filter: "progressive",
    advisory_warnings: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.profileSchema).mockResolvedValue({
      encoder: "x264",
      detail_level: "beginner",
      fields: [
        {
          name: "crf",
          group: "rate_control",
          introduced_at: "beginner",
          required: true,
          default: 18,
          value_type: "number",
          minimum: 0,
          maximum: 51,
          choices: [],
          description: "Minőség",
        },
      ],
    });
    vi.mocked(api.profileRecommendation).mockResolvedValue({
      source: "deterministic_expert_rules",
      requires_operator_confirmation: true,
      settings: { crf: 18, preset: "slow", profile: "high" },
    });
    vi.mocked(api.aiRecommendationStatus).mockResolvedValue({
      provider: "openai",
      configured: true,
      model: "gpt-test",
      structured_output: true,
      requires_operator_confirmation: true,
    });
    vi.mocked(api.aiRecommendation).mockResolvedValue({
      source: "openai_responses_api",
      provider: "openai",
      model: "gpt-test",
      requires_operator_confirmation: true,
      settings: { crf: 16.5, preset: "slower", tune: "grain" },
      temporal_filter: "progressive",
      summary: "Magas minőségű, szemcsemegőrző beállítás.",
      rationale: ["A scan progresszív 1080p filmet mutat."],
      warnings: ["A célméret CRF mellett tájékoztató."],
      confidence: 0.91,
    });
    vi.mocked(api.aitherPresets).mockResolvedValue({ encoder: "x264", requires_operator_confirmation: true, presets: [] });
    vi.mocked(api.noiseProfiles).mockResolvedValue({
      encoder: "x264",
      requires_operator_confirmation: true,
      profiles: [
        { id: "off", label: "Nincs", description: "Nincs külön kezelés.", settings: { noise_reduction: 0, tune: "film" } },
        { id: "medium_denoise", label: "Közepes zajszűrés", description: "nr 120", settings: { noise_reduction: 120, tune: "film" } },
      ],
    });
    vi.mocked(api.profileLibrary).mockResolvedValue({
      count: 1,
      items: [
        {
          id: "kedvenc",
          name: "Kedvenc",
          description: "",
          encoder: "x264",
          detail_level: "beginner",
          settings: { crf: 16.5 },
          auto_crf: { enabled: true, target_vmaf: 93 },
          created_at: "2026-05-01T10:00:00+00:00",
          updated_at: "2026-05-01T10:00:00+00:00",
          selection: { detail_level: "beginner", settings: { crf: 16.5 }, auto_crf: { enabled: true, target_vmaf: 93 } },
        },
      ],
    });
    vi.mocked(api.validateSelection).mockResolvedValue(validation);
    vi.mocked(api.saveSelection).mockResolvedValue(
      makeJob({ state: "READY", version: 2 }),
    );
  });

  it("leaves optional encoder tools to the preset until they are set, and explains them", async () => {
    const user = userEvent.setup();
    const optionalField = (name: string, valueType: "boolean" | "number", group: string) => ({
      name,
      group,
      introduced_at: "pro" as const,
      required: false,
      default: null,
      value_type: valueType,
      minimum: valueType === "number" ? 1 : null,
      maximum: valueType === "number" ? 3 : null,
      choices: [],
      description: "",
      optional: true,
    });
    vi.mocked(api.profileSchema).mockResolvedValue({
      encoder: "x264",
      detail_level: "beginner",
      fields: [optionalField("mbtree", "boolean", "x264"), optionalField("ipratio", "number", "rate_control")],
    });
    renderApp(<SelectionWizard job={makeJob({ state: "AWAITING_SELECTION", settings: { detail_level: "beginner" } })} scan={makeScan()} onComplete={vi.fn()} />);
    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Tovább" }));

    const mbtree = await screen.findByRole("combobox", { name: "Macroblock-tree (mbtree)" });
    expect(mbtree).toHaveValue("");
    const ipratio = screen.getByRole("spinbutton", { name: "I/P arány" });
    expect(ipratio).toHaveAttribute("placeholder", "preset szerint");
    await user.selectOptions(mbtree, "false");
    await user.type(ipratio, "1.3");

    await user.click(screen.getByRole("button", { name: "Macroblock-tree (mbtree): súgó" }));
    expect(screen.getByRole("dialog", { name: "Súgó: Macroblock-tree (mbtree)" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Bezárás" }).at(-1)!);

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Terv ellenőrzése" }));
    await waitFor(() => expect(api.validateSelection).toHaveBeenCalled());
    const sent = vi.mocked(api.validateSelection).mock.calls.at(-1)![1].video.settings;
    expect(sent).toMatchObject({ mbtree: false, ipratio: 1.3 });
  });

  it("walks through playlist, tracks and video before server validation and save", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    const job = makeJob({ state: "AWAITING_SELECTION", settings: { detail_level: "beginner" } });

    renderApp(<SelectionWizard job={job} scan={makeScan()} onComplete={onComplete} />);

    expect(screen.getByText("Playlist 00001")).toBeInTheDocument();
    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByRole("heading", { name: "Hangsávok" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("forrás: eng")).toBeInTheDocument();
    for (const label of ["Copy", "FLAC", "AC-3", "E-AC-3", "DTS", "Kihagyás"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: "E-AC-3" }));
    expect(screen.getByText(/1024 kb\/s · 48 kHz · legfeljebb 5\.1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByRole("heading", { name: "Ajánlott profil" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    const strictMatch = screen.getByRole("checkbox", { name: "Szigorú I/P/B típusazonosság kötelező" });
    expect(strictMatch).toBeChecked();
    expect(strictMatch).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Képtárhely"), "catbox");
    expect(screen.getByRole("combobox", { name: "Feltöltött képek köre" })).toHaveValue("all");
    await user.selectOptions(screen.getByRole("combobox", { name: "Feltöltött képek köre" }), "sdr");
    await user.click(screen.getByRole("button", { name: "Terv ellenőrzése" }));

    expect(await screen.findByText("A terv érvényes")).toBeInTheDocument();
    expect(api.validateSelection).toHaveBeenCalledWith(
      "job-1",
      expect.objectContaining({
        playlist_id: "00001",
        output_name: "Mintafilm.1080p.BluRay.x264",
        video: expect.objectContaining({
          detail_level: "beginner",
          settings: expect.objectContaining({ crf: 18 }),
        }),
        tracks: [expect.objectContaining({ stream_id: "audio:4352", action: "eac3", language: null })],
        image_upload_provider: "catbox",
        upload_image_set: "sdr",
        dual_type_match: true,
      }),
      1,
    );
    const submittedTracks = vi.mocked(api.validateSelection).mock.calls[0][1].tracks;
    expect(submittedTracks[0]).not.toHaveProperty("forced");
    expect(submittedTracks[0]).not.toHaveProperty("subtitle_kind");

    await user.click(
      screen.getByRole("button", { name: "Jóváhagyás és automatikus indítás" }),
    );
    await waitFor(() => expect(api.saveSelection).toHaveBeenCalledTimes(1));
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("shows the steps, track actions and buttons in English", async () => {
    setLanguage("en", { persist: false });
    const user = userEvent.setup();
    renderApp(<SelectionWizard job={makeJob({ state: "AWAITING_SELECTION", settings: { detail_level: "beginner" } })} scan={makeScan()} onComplete={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "Encoding settings" })).toBeInTheDocument();
    for (const step of [/^1\s*Playlist$/, /^2\s*Tracks$/, /^3\s*Video$/, /^4\s*Check$/]) {
      expect(screen.getByRole("button", { name: step })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Audio tracks" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Omit" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("source: eng")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Tracker profile" }), "aither");
    await user.click(screen.getByRole("button", { name: "Arrange tracks (Aither)" }));
    expect(screen.getByText("What changed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Recommended profile" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Beginner" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask for an AI suggestion" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("button", { name: /Suggest name/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Image host" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check plan" })).toBeInTheDocument();
  });

  it("arranges the tracks for nCore, suggests a Hungarian release name and shows the tracker findings", async () => {
    const user = userEvent.setup();
    window.localStorage.removeItem("bdencode.release-tag");
    vi.mocked(api.validateSelection).mockResolvedValue({
      ...validation,
      tracker_profile: "ncore",
      tracker_findings: [{ code: "ncore_channels", severity: "warning", message: "Az angol hang 7.1 helyett 5.1 lett." }],
    });
    renderApp(<SelectionWizard job={makeJob({ state: "AWAITING_SELECTION" })} scan={makeScanWithTrueHdAndHungarianDub()} onComplete={vi.fn()} />);
    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.selectOptions(screen.getByLabelText("Tracker-profil"), "ncore");
    await user.click(screen.getByRole("button", { name: "Sávterv igazítása (nCore)" }));
    expect(screen.getByText(/E-AC3 \(DD\+\) 5\.1, 1024 kbps lesz/)).toBeInTheDocument();
    const order = screen.getByRole("list", { name: "Kimeneti sávsorrend" });
    expect(order.querySelectorAll("li")[0]).toHaveTextContent(/hun.*alapértelmezett/);
    expect(order.querySelectorAll("li")[1]).toHaveTextContent(/eng · EAC3 5\.1/);

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.type(screen.getByLabelText("Release-tag"), "TAG");
    await user.click(screen.getByRole("button", { name: "Név javaslata (magyar szabvány)" }));
    expect(screen.getByDisplayValue("Mintafilm.1080p.BluRay.DDP5.1.x264.HUN-TAG")).toBeInTheDocument();
    expect(window.localStorage.getItem("bdencode.release-tag")).toBe("TAG");

    await user.click(screen.getByRole("button", { name: "Terv ellenőrzése" }));
    expect(await screen.findByText("Az angol hang 7.1 helyett 5.1 lett.")).toBeInTheDocument();
    expect(api.validateSelection).toHaveBeenCalledWith(
      "job-1",
      expect.objectContaining({
        tracker_profile: "ncore",
        output_name: "Mintafilm.1080p.BluRay.DDP5.1.x264.HUN-TAG",
        tracks: [
          expect.objectContaining({ stream_id: "audio:4352", action: "eac3", order: 1, default: false }),
          expect.objectContaining({ stream_id: "audio:4353", action: "copy", order: 0, default: true }),
        ],
      }),
      1,
    );
  });

  it("opens a malformed NEEDS_REVIEW selection with scan-derived repair defaults", async () => {
    const user = userEvent.setup();
    const job = makeJob({
      state: "NEEDS_REVIEW",
      selection: { unexpected: "legacy-or-corrupt-payload" },
      settings: { detail_level: "beginner" },
    });

    renderApp(<SelectionWizard job={job} scan={makeScan()} onComplete={vi.fn()} />);

    expect(screen.getByText("Playlist 00001")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByRole("heading", { name: "Hangsávok" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("forrás: eng")).toBeInTheDocument();
  });

  it("shows the track analysis and accepts all suggestions in one click", async () => {
    const scan = makeScan();
    const playlist = scan.playlists[0];
    const audio = playlist.streams.find((stream) => stream.kind === "audio")!;
    const subtitle = (id: string, pid: number) => ({
      ...audio,
      id,
      pid,
      kind: "subtitle" as const,
      codec: "hdmv_pgs_subtitle",
      title: null,
      channels: null,
      channel_layout: null,
      sample_rate: null,
      default: true,
    });
    playlist.streams = [...playlist.streams, subtitle("subtitle:4608", 4608), subtitle("subtitle:4609", 4609)];
    playlist.track_analysis = {
      schema_version: 1,
      windows: Array.from({ length: 6 }, (_, index) => ({ start_seconds: 600 + index * 900, duration_seconds: 30 })),
      audio: { [audio.id]: { status: "detected", iso639_2t: "hun", confidence: 0.94, agreement: 1, usable_samples: 6, needs_review: false, reason: "consensus" } },
      subtitles: {
        "subtitle:4608": { events: 31, sampled_seconds: 180, events_per_minute: 10.33, suggested_kind: "full", confidence: "high" },
        "subtitle:4609": { events: 1, sampled_seconds: 180, events_per_minute: 0.33, suggested_kind: "forced", confidence: "high" },
      },
    };
    const user = userEvent.setup();
    const view = renderApp(<SelectionWizard job={makeJob({ state: "AWAITING_SELECTION" })} scan={scan} onComplete={vi.fn()} />);

    await user.click(view.getByRole("button", { name: "Tovább" }));
    expect(view.getByText("Sávelemzés a lemezből")).toBeInTheDocument();
    expect(view.getByText(/A lemez szerint eng, a hang alapján/)).toBeInTheDocument();
    expect(view.getByText(/Javaslat: Teljes felirat \(31 esemény 3 perc mintában/)).toBeInTheDocument();
    expect(view.getByText(/Javaslat: Forced \/ signs/)).toBeInTheDocument();
    const kinds = view.getAllByRole("combobox", { name: /felirattípusa/ });
    expect(kinds.map((select) => (select as HTMLSelectElement).value)).toEqual(["unknown", "unknown"]);

    await user.click(view.getByRole("button", { name: "Minden javaslat elfogadása (3)" }));

    expect(kinds.map((select) => (select as HTMLSelectElement).value)).toEqual(["full", "forced"]);
    expect(view.getByRole("textbox", { name: "English 5.1 nyelve" })).toHaveValue("hun");
    expect(view.queryByRole("button", { name: /Minden javaslat elfogadása/ })).not.toBeInTheDocument();
  });

  it("requests a scan-aware AI profile and applies only editable fields", async () => {
    const user = userEvent.setup();
    const view = renderApp(
      <SelectionWizard
        job={makeJob({ state: "AWAITING_SELECTION" })}
        scan={makeScan()}
        onComplete={vi.fn()}
      />,
    );

    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    expect(view.getByRole("heading", { name: "AI beállítási tanácsadó" })).toBeInTheDocument();
    await waitFor(() => expect(view.getByRole("button", { name: "AI-javaslat kérése" })).toBeEnabled());
    await user.type(view.getByRole("spinbutton", { name: /Kívánt méret/ }), "12");
    await user.type(view.getByRole("textbox", { name: /Műfaj/ }), "film noir");
    await user.click(view.getByRole("button", { name: "AI-javaslat kérése" }));

    expect(await view.findByText("Magas minőségű, szemcsemegőrző beállítás.")).toBeInTheDocument();
    expect(api.aiRecommendation).toHaveBeenCalledWith("job-1", expect.objectContaining({
      playlist_id: "00001",
      detail_level: "beginner",
      quality_priority: "balanced",
      target_size_gib: 12,
      genre: "film noir",
    }));
    await user.click(view.getByRole("button", { name: "Javaslat alkalmazása a mezőkre" }));
    expect(view.getByRole("spinbutton", { name: /CRF minőség/ })).toHaveValue(16.5);
    expect(view.getByText(/bekerült a szerkeszthető mezőkbe/)).toBeInTheDocument();
  });

  it("offers a provider choice when both AI keys are set and sends the chosen one", async () => {
    vi.mocked(api.aiRecommendationStatus).mockResolvedValue({
      provider: "openai",
      configured: true,
      model: "gpt-test",
      default_provider: null,
      providers: [
        { id: "openai", label: "OpenAI", credential: "openai-api-key", configured: true, model: "gpt-test", default_model: "gpt-test" },
        { id: "anthropic", label: "Claude (Anthropic)", credential: "anthropic-api-key", configured: true, model: "claude-opus-5-5", default_model: "claude-opus-5-5" },
      ],
      structured_output: true,
      requires_operator_confirmation: true,
    });
    const user = userEvent.setup();
    const view = renderApp(
      <SelectionWizard
        job={makeJob({ state: "AWAITING_SELECTION" })}
        scan={makeScan()}
        onComplete={vi.fn()}
      />,
    );

    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    const choice = await view.findByRole("combobox", { name: "AI szolgáltató" });
    await user.selectOptions(choice, "anthropic");
    expect(view.getByText(/Claude \(Anthropic\) API-nak/)).toBeInTheDocument();
    await user.click(view.getByRole("button", { name: "AI-javaslat kérése" }));

    await waitFor(() => expect(api.aiRecommendation).toHaveBeenCalledWith("job-1", expect.objectContaining({ provider: "anthropic" })));
  });

  it("does not leave the track step while a retained subtitle is unclassified", async () => {
    const user = userEvent.setup();
    const view = renderApp(
      <SelectionWizard
        job={makeJob({ state: "AWAITING_SELECTION" })}
        scan={makeScanWithRetainedSubtitle()}
        onComplete={vi.fn()}
      />,
    );

    await user.click(view.getByRole("button", { name: "Tovább" }));

    expect(view.getByText("Felirattípus megadása szükséges")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Tovább" })).toBeDisabled();

    await user.selectOptions(view.getByLabelText("Magyar felirattípusa"), "full");

    expect(view.getByRole("button", { name: "Tovább" })).toBeEnabled();
  });

  it("lists missing source color fields and sends the explicitly confirmed BD defaults", async () => {
    const user = userEvent.setup();
    const scan = makeScan();
    const sourceVideo = scan.playlists[0].streams[0].video;
    if (!sourceVideo) throw new Error("A teszt videósávja hiányzik");
    scan.playlists[0].streams[0] = {
      ...scan.playlists[0].streams[0],
      video: {
        ...sourceVideo,
        color_primaries: null,
        color_transfer: null,
        color_matrix: null,
      },
    };
    const job = makeJob({ state: "AWAITING_SELECTION", settings: { detail_level: "beginner" } });

    const view = renderApp(<SelectionWizard job={job} scan={scan} onComplete={vi.fn()} />);
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));

    expect(view.getByRole("heading", { name: "Forrás színinformációjának megerősítése" })).toBeInTheDocument();
    expect(view.getByText("Színprimerek", { selector: ".badge" })).toBeInTheDocument();
    expect(view.getByText("Átviteli karakterisztika", { selector: ".badge" })).toBeInTheDocument();
    expect(view.getByText("Mátrixegyütthatók", { selector: ".badge" })).toBeInTheDocument();
    expect(view.getByText("Ajánlott alapérték: SDR Blu-ray · BT.709")).toBeInTheDocument();

    await user.click(view.getByRole("button", { name: "Ezeknek az értékeknek a jóváhagyása" }));
    expect(view.getByText("Jóváhagyva")).toBeInTheDocument();

    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Terv ellenőrzése" }));
    await waitFor(() => expect(api.validateSelection).toHaveBeenCalled());
    expect(api.validateSelection).toHaveBeenCalledWith(
      "job-1",
      expect.objectContaining({
        video: expect.objectContaining({
          settings: expect.objectContaining({
            color: {
              primaries: "bt709",
              transfer: "bt709",
              matrix: "bt709",
              range: "limited",
              chroma_location: "left",
            },
          }),
        }),
      }),
      1,
    );
  });

  it("turns the structured source color API error into an actionable Hungarian message", async () => {
    const user = userEvent.setup();
    vi.mocked(api.validateSelection).mockRejectedValueOnce(new ApiError(
      422,
      "source color metadata is incomplete; confirm it before encoding",
      {
        detail: "source color metadata is incomplete; confirm it before encoding",
        code: "source_color_confirmation_required",
        context: {
          missing_fields: ["primaries", "matrix"],
          suggested: {
            primaries: "bt709",
            transfer: "bt709",
            matrix: "bt709",
            range: "limited",
            chroma_location: "left",
          },
        },
      },
    ));

    const view = renderApp(<SelectionWizard job={makeJob({ state: "AWAITING_SELECTION" })} scan={makeScan()} onComplete={vi.fn()} />);
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Terv ellenőrzése" }));

    expect(await view.findByText("Hiányos forrás-színinformáció")).toBeInTheDocument();
    expect(view.getAllByText(/Színprimerek, Mátrixegyütthatók/)).toHaveLength(2);
    await user.click(view.getByRole("button", { name: "Színadatok megnyitása" }));
    expect(view.getByRole("heading", { name: "Forrás színinformációjának megerősítése" })).toBeInTheDocument();
    expect(view.queryByText(/source color metadata is incomplete/i)).not.toBeInTheDocument();
  });

  it("turns a backend subtitle classification error into a Hungarian repair action", async () => {
    const user = userEvent.setup();
    vi.mocked(api.validateSelection).mockRejectedValueOnce(new ApiError(
      422,
      "tracks[3] retained subtitle needs an explicit full/forced classification",
      { detail: "tracks[3] retained subtitle needs an explicit full/forced classification" },
    ));
    const view = renderApp(
      <SelectionWizard
        job={makeJob({ state: "AWAITING_SELECTION" })}
        scan={makeScanWithRetainedSubtitle()}
        onComplete={vi.fn()}
      />,
    );

    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.selectOptions(view.getByLabelText("Magyar felirattípusa"), "forced");
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Terv ellenőrzése" }));

    expect(await view.findByText("Hiányzik egy megtartott felirat típusa")).toBeInTheDocument();
    expect(view.queryByText(/retained subtitle needs/i)).not.toBeInTheDocument();

    await user.click(view.getByRole("button", { name: "Feliratok megnyitása" }));
    expect(view.getByRole("heading", { name: "Feliratok" })).toBeInTheDocument();
  });

  it("repairs the legacy audio-only subtitle fields and retries validation", async () => {
    const user = userEvent.setup();
    vi.mocked(api.validateSelection).mockRejectedValueOnce(new ApiError(
      422,
      "selection cannot be planned safely: audio tracks cannot define forced or subtitle_kind fields",
      { detail: "selection cannot be planned safely: audio tracks cannot define forced or subtitle_kind fields" },
    ));
    const view = renderApp(
      <SelectionWizard
        job={makeJob({
          state: "AWAITING_SELECTION",
          selection: {
            playlist_id: "00001",
            tracks: [{
              stream_id: "audio:4352",
              action: "copy",
              default: true,
              forced: false,
              subtitle_kind: null,
              order: 0,
            }],
          },
        })}
        scan={makeScan()}
        onComplete={vi.fn()}
      />,
    );

    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Tovább" }));
    await user.click(view.getByRole("button", { name: "Terv ellenőrzése" }));

    expect(await view.findByText("A hangsáv hibás feliratjelölést tartalmazott")).toBeInTheDocument();
    expect(view.queryByText(/audio tracks cannot define/i)).not.toBeInTheDocument();

    const firstPayload = vi.mocked(api.validateSelection).mock.calls[0][1];
    expect(firstPayload.tracks[0]).not.toHaveProperty("forced");
    expect(firstPayload.tracks[0]).not.toHaveProperty("subtitle_kind");

    await user.click(view.getByRole("button", { name: "Terv újraellenőrzése" }));
    expect(await view.findByText("A terv érvényes")).toBeInTheDocument();
    expect(api.validateSelection).toHaveBeenCalledTimes(2);
  });

  it("sends the automatic CRF search, a noise preset and a library profile with the selection", async () => {
    const user = userEvent.setup();
    renderApp(
      <SelectionWizard job={makeJob({ state: "AWAITING_SELECTION" })} scan={makeScan()} onComplete={vi.fn()} />,
    );

    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "E-AC-3" }));
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(screen.getByRole("heading", { name: "Minőségi opciók" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Dinamikus HDR")).not.toBeInTheDocument();

    // A noise preset merges its concrete settings into the editable fields.
    const noise = await screen.findByLabelText("Zaj- és szemcseprofil");
    await waitFor(() => expect(noise).toBeEnabled());
    await user.selectOptions(noise, "medium_denoise");

    // Turning the automatic CRF search on and tuning its target.
    await user.click(screen.getByRole("checkbox", { name: /A worker rövid mintakódolásokból/ }));
    const target = screen.getByLabelText("Cél VMAF");
    await user.clear(target);
    await user.type(target, "94.5");

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Terv ellenőrzése" }));

    await waitFor(() => expect(api.validateSelection).toHaveBeenCalledTimes(1));
    const video = vi.mocked(api.validateSelection).mock.calls[0][1].video;
    expect(video.auto_crf).toEqual({ enabled: true, target_vmaf: 94.5 });
    expect(video.settings).toEqual(expect.objectContaining({ noise_reduction: 120, tune: "film" }));
    expect(video).not.toHaveProperty("dynamic_hdr");
  });

  it("applies a library profile: its settings, automatic CRF and HDR policy replace the editable state", async () => {
    const user = userEvent.setup();
    renderApp(
      <SelectionWizard job={makeJob({ state: "AWAITING_SELECTION" })} scan={makeScan()} onComplete={vi.fn()} />,
    );

    await waitFor(() => expect(api.profileRecommendation).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "E-AC-3" }));
    await user.click(screen.getByRole("button", { name: "Tovább" }));

    await user.click(await screen.findByRole("button", { name: "Kedvenc alkalmazása" }));
    expect(screen.getByLabelText("Cél VMAF")).toHaveValue(93);

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Terv ellenőrzése" }));

    await waitFor(() => expect(api.validateSelection).toHaveBeenCalledTimes(1));
    const video = vi.mocked(api.validateSelection).mock.calls[0][1].video;
    expect(video.auto_crf).toEqual({ enabled: true, target_vmaf: 93 });
    expect(video.settings).toEqual(expect.objectContaining({ crf: 16.5 }));
  });

  it("restores the saved quality options when a selection is reopened", async () => {
    const user = userEvent.setup();
    const job = makeJob({
      state: "NEEDS_REVIEW",
      selection: {
        schema_version: 2,
        playlist_id: "00001",
        angle: 1,
        video: {
          detail_level: "beginner",
          temporal_filter: "progressive",
          crop: { left: 0, top: 0, right: 0, bottom: 0 },
          settings: { crf: 17 },
          auto_crf: { enabled: true, target_vmaf: 92 },
        },
        tracks: [],
        output_name: "Mintafilm.1080p.BluRay.x264",
        upload_images: false,
      },
    });
    renderApp(<SelectionWizard job={job} scan={makeScan()} onComplete={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Tovább" }));
    await user.click(screen.getByRole("button", { name: "Tovább" }));
    expect(await screen.findByLabelText("Cél VMAF")).toHaveValue(92);
  });
});
