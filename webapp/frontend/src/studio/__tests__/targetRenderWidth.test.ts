import { describe, it, expect } from "vitest";
import {
  targetRenderWidth,
  HI_DPI_BASELINE_PX,
  HI_DPI_MAX_PX,
} from "../Studio";

describe("targetRenderWidth (FEATURES #43 zoom-aware re-render)", () => {
  it("never goes below the baseline at fit/low zoom", () => {
    // 1512 × 1 × 2 = 3024 → below baseline → clamped up to 8000
    expect(targetRenderWidth(1512, 1, 2)).toBe(HI_DPI_BASELINE_PX);
    expect(targetRenderWidth(1280, 0.5, 1)).toBe(HI_DPI_BASELINE_PX);
  });

  it("never exceeds the max (must match the backend cap)", () => {
    // 1512 × 6 × 2 = 18144 → clamped down to 12000
    expect(targetRenderWidth(1512, 6, 2)).toBe(HI_DPI_MAX_PX);
    expect(targetRenderWidth(3000, 4, 2)).toBe(HI_DPI_MAX_PX);
  });

  it("rounds the target UP to the bucket so wheel-notches don't thrash", () => {
    // 1512 × 3 × 2 = 9072 → ceil to 10000 (bucket 2000)
    expect(targetRenderWidth(1512, 3, 2)).toBe(10000);
    // 1500 × 3 × 2 = 9000 → already a bucket multiple, stays 10000? 9000→10000
    expect(targetRenderWidth(1500, 3, 2)).toBe(10000);
  });

  it("increases monotonically with zoom (caller relies on this to only sharpen)", () => {
    const w1 = targetRenderWidth(1400, 2, 2);
    const w2 = targetRenderWidth(1400, 3, 2);
    const w3 = targetRenderWidth(1400, 5, 2);
    expect(w1).toBeLessThanOrEqual(w2);
    expect(w2).toBeLessThanOrEqual(w3);
  });

  it("accounts for devicePixelRatio (Retina needs more pixels at the same zoom)", () => {
    // zoom 3: dpr1 = 1512×3×1 = 4536 → clamps up to baseline 8000;
    //         dpr2 = 1512×3×2 = 9072 → bucket 10000 (past baseline).
    expect(targetRenderWidth(1512, 3, 1)).toBe(HI_DPI_BASELINE_PX);
    expect(targetRenderWidth(1512, 3, 2)).toBeGreaterThan(HI_DPI_BASELINE_PX);
  });
});
