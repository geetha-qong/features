import { describe, it, expect } from "vitest";
import { detectionPage } from "../Studio";

describe("detectionPage (per-sheet sidebar filter)", () => {
  it("parses the page from the tile filename", () => {
    expect(detectionPage({ tile: "tile_p0_r1_c2.png" })).toBe(0);
    expect(detectionPage({ tile: "tile_p3_r0_c0.png" })).toBe(3);
  });
  it("falls back to an explicit page field when no tile match", () => {
    expect(detectionPage({ page: 2 })).toBe(2);
    expect(detectionPage({ tile: "no-page-here.png", page: 1 })).toBe(1);
  });
  it("prefers the tile filename over the page field", () => {
    expect(detectionPage({ tile: "tile_p2_r0_c0.png", page: 5 })).toBe(2);
  });
  it("returns null when neither is resolvable (kept by the filter)", () => {
    expect(detectionPage({})).toBeNull();
    expect(detectionPage({ tile: "garbage.png" })).toBeNull();
  });
});
