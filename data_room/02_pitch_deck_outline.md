# Qong — Pitch Deck Outline (10 Slides)

*Slide-by-slide narrative with speaker notes and key data points*

---

## Slide 1 — Title

**Headline**: "P&ID valve lists in minutes, not days"

**Subheadline**: AI-powered extraction from scanned engineering drawings

**Visual**: Side-by-side — raw P&ID drawing (left) → clean CSV spreadsheet (right)

**Bottom**: Qong | dev.theqong.com | [date]

---

## Slide 2 — The Problem

**Headline**: "Every oil & gas project starts with thousands of hours of manual drawing work"

**Key stats** (large text):
- **500–2,000 P&ID drawings** per greenfield project
- **3–4 hours** per drawing to manually extract valve data
- **$150K–$800K** per project in engineer time, for this one task alone
- **High error rate** — wrong tag numbers, missed valves, wrong pipe class

**Visual**: Photo of an engineer at a desk with a printed P&ID and a spreadsheet. Or: a zoomed P&ID with dense valve symbols circled.

**Speaker note**: "Every P&ID contains dozens of valves. Before any construction begins, someone has to read every one, find its tag number, read the pipe label next to it, note any actuator, and type it into a spreadsheet. There is no software that does this automatically for scanned drawings. Engineers do it by hand. Every time. On every project."

---

## Slide 3 — The Solution

**Headline**: "Upload a drawing. Download the valve list."

**3-step visual**:
```
[PDF Upload Icon]   →   [AI Processing Icon]   →   [CSV Download Icon]
  Raw P&ID PDF          AI reads symbols,            Structured valve list
  (any scan)            tags & line numbers          ready to use in 3 min
```

**Key claim**: ≥90% recall. Works on any scanned P&ID. No structured data required.

**Speaker note**: "We built a pipeline that renders the PDF at high resolution, tiles it into sections, sends each section to an AI vision model trained to read P&ID notation, then parses and deduplicates the results into a clean CSV. The engineer gets in 3 minutes what used to take 3 hours."

---

## Slide 4 — How It Works (Technical, Keep Simple)

**Headline**: "Under the hood — built for accuracy, not magic"

**Simple pipeline diagram**:
```
PDF → [Tile into sections] → [AI Vision reads each tile] → [Parser] → [Validator] → CSV
```

**3 key accuracy features**:
1. **25% overlap between tiles** — no valve is missed at a boundary
2. **Legends-aware** — AI knows all valve symbol types from the project legend
3. **Deduplication** — same valve appearing in two tiles counted once

**Current stack**: Python · FastAPI · PyMuPDF · Claude Vision API · SQLite

**Speaker note**: "The tile overlap is the key insight. P&ID drawings are huge — if you just cut them into sections, you'll miss anything at the cut line. By overlapping sections 25%, every valve appears in at least one complete tile. The AI never sees a half-cut symbol."

---

## Slide 5 — Market Size

**Headline**: "A $3B market that has barely started digitizing"

**TAM / SAM / SOM** (nested circles):
- **TAM**: $3.2B — Global P&ID software and plant digitization market (growing 8% CAGR)
- **SAM**: ~$800M — Valve and instrument list extraction across EPC and owner-operator projects
- **SOM**: ~$40M — Top 50 EPC contractors, 20 projects/year each, $40/drawing avg

**Supporting data**:
- ~500,000 active oil & gas and petrochemical facilities globally
- Each with hundreds to thousands of P&IDs
- Industry is under regulatory pressure to digitize (ISO 15926, DEXPI standard)

**Speaker note**: "The TAM here is the broader P&ID digitization market. We're entering at the most painful, most automatable slice: valve list extraction. But the same pipeline that reads valves can be extended to instruments, equipment, pipelines — the full drawing."

---

## Slide 6 — Business Model

**Headline**: "Simple pricing, strong unit economics"

**Three tiers**:

| Model | Price | Who |
|-------|-------|-----|
| Per-drawing | $10–50 / P&ID | SME firms, one-off projects |
| SaaS | $500–2,000 / month per team | Mid-size EPC contractors |
| Enterprise | Custom annual license | Shell, Aramco scale |

**Unit economics**:
- API cost per drawing: ~$0.10–0.50
- Revenue per drawing: $10–50
- **Gross margin: 80–99%**

**Phase 2 unit economics** (own model):
- API cost → $0.00 (own model, own compute)
- Gross margin → 95%+

**Speaker note**: "The model is deliberately simple to sell. A project manager can approve a per-drawing fee without procurement. For larger customers we move to a monthly SaaS. The gross margin is extraordinary because the marginal cost is one API call."

---

## Slide 7 — Competitive Landscape

**Headline**: "No one solves this problem for scanned drawings at this price"

**Comparison table**:

| | Qong | Manual (Excel) | AVEVA E3D | SmartPlant P&ID |
|--|------|---------------|-----------|-----------------|
| Works on scanned PDFs | ✅ | ✅ (manual) | ❌ requires structured data | ❌ requires structured data |
| Time per drawing | 3 min | 3–4 hours | N/A (authoring tool) | N/A (authoring tool) |
| Cost per drawing | $10–50 | $300–400 | $500K+ license | $500K+ license |
| Output format | Standard CSV | Custom | Proprietary | Proprietary |
| Requires P&ID redraw | ❌ | ❌ | ✅ | ✅ |

**Speaker note**: "AVEVA and SmartPlant are the enterprise incumbents — but they require the P&ID to be redrawn inside their software. That costs millions and takes years. Our customers have 30 years of legacy drawings on scanned PDFs. We work on what they have today."

---

## Slide 8 — Traction

**Headline**: "From idea to live product in 2 weeks — on real drawings"

**Metrics**:
- ✅ **Live product** at dev.theqong.com (upload, process, download)
- ✅ **Real drawings** — tested on Occidental Mukhaizna LLC (Oman) P&IDs
- ✅ **27 valves extracted** from initial drawing, ≥90% recall
- ✅ **Full CI/CD pipeline** — webhook auto-deploy on Ubuntu VPS
- ✅ **$20/month** total infrastructure cost (VPS + storage)

**Screenshots**: [webapp login / dashboard / job results — screenshots from dev.theqong.com]

**Speaker note**: "We didn't build a demo. We built a working product on a real client's drawings. The Mukhaizna P&ID from Oman is a 4,768 × 3,368 pixel scanned image — no embedded text — and we extracted 27 valves in under 3 minutes."

---

## Slide 9 — Team

**Headline**: "Built by engineers who understand the problem"

[Founder 1]
- Background
- Domain expertise
- LinkedIn

[Founder 2 / Advisor]
- Background
- Oil & gas or software experience
- LinkedIn

**Domain advisors**: [P&ID engineers, oil & gas project managers]

**Why us**: We understand both the engineering domain (P&ID notation, EPC workflows) and the AI/software stack to automate it. This is not a generic AI wrapper — it requires deep domain knowledge to validate outputs and design the extraction logic.

---

## Slide 10 — The Ask

**Headline**: "Raising $[X] to move from POC to product"

**Round**: Seed | $[X]M | [SAFE / priced round]

**Use of funds**:
```
40% — Engineering
       Phase 2: own CV model (YOLO + PaddleOCR)
       Extended scope: instruments, equipment items
30% — Sales & Customer Success
       Land 3–5 pilot EPC customers
       Build case studies + accuracy benchmarks
20% — Infrastructure & Compute
       GPU training runs, production scaling
10% — Legal, IP, operations
       IP filings, TOS, company setup
```

**12-month milestones**:
- Month 3: 3 paying pilot customers
- Month 6: Own OCR model in production (zero API cost)
- Month 9: Instrument extraction live (scope expansion)
- Month 12: $[X] ARR, 10+ active customers

**The long-term vision**: Full P&ID-to-digital-twin conversion. Every pipe, valve, instrument, and equipment item extracted automatically — the data layer for AI-powered plant operations.

---

## Appendix Slides (have ready, don't pitch)

- A1: Full accuracy benchmark table (drawing-by-drawing)
- A2: Technical architecture deep-dive
- A3: Phase 2 model training plan (YOLO dataset, annotation pipeline)
- A4: Detailed financial projections (3-year)
- A5: Customer discovery quotes / interview excerpts
- A6: Regulatory tailwinds (ISO 15926, DEXPI, digital twin mandates)
