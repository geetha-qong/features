# Patent Analysis — Qong P&ID Extraction Product

## Patent Landscape Assessment

### Existing Prior Art

1. **US10635945B2 — Schneider Electric** (Granted, Active until 2038)
   - Covers ML-based P&ID analysis: symbol detection via CNNs, tag extraction, character segmentation, feedback/retraining loop
   - Filed: June 28, 2018 | [Google Patents](https://patents.google.com/patent/US10635945B2/en)

2. **Academic Research** (2019+)
   - [Automatic Information Extraction from P&IDs](https://arxiv.org/abs/1901.11383) — Arxiv 2019
   - [Automated Valve Detection in P&ID Diagrams](https://asu.elsevierpure.com/en/publications/automated-valve-detection-in-piping-and-instrumentation-pampid-di) — ASU, ISARC 2022
   - [Fine-Tuning VLM for Engineering Drawing Extraction](https://arxiv.org/abs/2411.03707) — Arxiv 2024
   - [Hybrid Vision-Language Framework for 2D Engineering Drawings](https://www.sciencedirect.com/science/article/abs/pii/S0736584525002406)

3. **Commercial Competitors Already Shipping**
   - AVEVA — AI-driven P&ID digitization, 157+ patents filed
   - SymphonyAI — P&ID ingestion product
   - Azati — AI-powered P&ID OCR digitization
   - DeepIQ — P&ID digitization service
   - IPS-AI — AI P&ID management
   - Hexagon — Intergraph Smart P&ID
   - Cognite — Industrial AI platform (Atlas AI)

### Schneider Electric Patent (US10635945B2) — Key Details

- **Status**: Active, expires 2038-12-12
- **Covers**: Computer-implemented method for extracting P&ID information using ML
- **Technical methods**:
  - Image conversion (PDF → PNG/JPEG/GIF)
  - Symbol detection via stepping-down + window-sliding algorithms
  - Multiple CNN architectures (circle detection, symbol recognition, character classification)
  - Tag extraction via vertical gap detection, pixel density analysis, sliding window
  - ML feedback loop for retraining based on errors
  - ISA-based rules validation for symbols and tags
- **Inventors**: Venkatesh Jagannath, Amitabha Bhattacharyya, Ashish Patil, Bhaskar Sinha, Sameer Kondejkar

### Qong's Potentially Novel Elements

| Aspect | Novelty Level | Notes |
|--------|--------------|-------|
| VLM (Claude Vision) instead of custom CNNs/YOLO | Partial | VLMs for P&ID valve extraction not yet patented specifically |
| Tiled extraction with overlapping grid + dedup | Weak | Tiling/overlap is standard image processing |
| Two-pass extraction (pass 1 tags, pass 2 missing line numbers) | Moderate | Iterative refinement for valve-line association could be novel |
| Domain-specific prompt engineering | Weak | Hard to patent and enforce |
| Edge deployment on Jetson (Phase 2/3) | N/A | Not built yet; can't patent |

### India Patent Requirements (2025 CRI Guidelines)

- Must demonstrate **"technical effect beyond normal software-hardware interaction"**
- AI inventions patentable if they show improved security, efficiency, robustness, or resource use
- Claims that merely automate a business rule on general-purpose hardware are excluded
- Human inventor required (AI cannot be listed as inventor)
- Cost: ~INR 1-4 lakhs for provisional + complete specification
- References:
  - [India AI Patent Eligibility](https://www.managingip.com/article/2c8q22uq5bhkzgreo35s0/sponsored-content/india-patent-eligibility-of-ai-related-inventions)
  - [India CRI Guidelines 2025](https://www.obhanandassociates.com/blog/india-upgrades-its-guidelines-for-computer-related-inventions/)

## Recommendation

### Don't Rely on Patents as Primary Moat

1. **Trade Secrets** — Prompt engineering, corrections framework, domain-specific parsing logic are better protected this way
2. **Speed to Market** — First working product in oil & gas P&ID space matters more
3. **Data/Accuracy Moat** — Every drawing processed improves corrections database; compounding advantage
4. **Provisional Filing** — File provisional patent in India (~INR 1-2 lakhs) to establish priority date while building Phase 2

### Stronger Patent Case for Phase 2

The current POC (API wrapper with tiling) is too close to prior art. But **Phase 2** — custom-trained YOLO + PaddleOCR on Jetson edge hardware, specifically optimized for P&ID valve detection — would be significantly more patentable:
- Custom trained model (not third-party API)
- Edge hardware deployment (specific technical implementation)
- Domain-specific optimization for valve/instrument detection
- Offline/air-gapped operation (security advantage)

### Action Items

- [ ] File provisional patent in India to secure priority date
- [ ] Build Phase 2 (YOLO + PaddleOCR on Jetson) to strengthen claims
- [ ] Document all novel methods thoroughly for patent specification
- [ ] Consult IP attorney specializing in software/AI patents in India

---

*Research date: March 5, 2026*
