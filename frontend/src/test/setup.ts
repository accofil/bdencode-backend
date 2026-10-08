import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { setLanguage } from "../i18n";

// The tests assert the Hungarian interface unless a test switches to English.
beforeEach(() => setLanguage("hu", { persist: false }));
afterEach(() => cleanup());
