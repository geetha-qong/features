# Qong — Executive Summary

## AI-Powered P&ID Valve List Extraction

**Live product**: https://dev.theqong.com | **Contact**: [founder contact]

---

## The Problem

Every oil & gas facility runs on P&IDs — piping and instrumentation diagrams that define the physical layout of every valve, instrument, and pipe. Before construction, commissioning, or maintenance can begin, engineers must manually extract **valve lists** from these drawings into spreadsheets.

**The manual process:**
- 2–4 hours per P&ID drawing, per engineer
- A typical greenfield project has 500–2,000 P&IDs
- **1,500–8,000 engineer-hours of manual work per project**
- At $100/hr loaded cost: **$150,000–$800,000 per project** in extraction labor alone
- Error rate: high — engineers miss valves, misread tag numbers, enter wrong pipe classes

This is entirely repetitive, rules-based work that engineers hate doing. It has not changed in 30 years.

---

## The Solution

**Upload a P&ID PDF. Get a structured valve list CSV in minutes.**

Qong uses AI vision to read scanned P&ID drawings the same way an expert engineer would — identifying every valve symbol, reading the tag label, extracting the adjacent pipe line number, and detecting any actuator attachments. No structured data required. Works on any scanned P&ID.

**Output**: A 14-column valve list (tag, size, fluid code, piping class, actuator type, area code, serial number) ready to import into AVEVA, SmartPlant, or project spreadsheets.

**Demonstrated accuracy**: ≥90% recall on real Occidental Mukhaizna (Oman) P&ID drawings.

**Processing time**: Under 3 minutes per drawing. Manual equivalent: 3–4 hours.

**Cost**: < $1 per P&ID in compute cost. Priced at $10–50/drawing or SaaS subscription.

---

## Market

| Segment | Description |
|---------|-------------|
| **TAM** | Global P&ID software & digitization market — $3.2B, growing 8% CAGR |
| **SAM** | Oil & gas EPC firms and owner-operators needing valve list extraction |
| **SOM** | Top 50 EPC contractors globally × 20 active projects each × $5,000/project avg |

**Target customers**: Worley, Wood PLC, Petrofac, Jacobs (EPC contractors); Shell, BP, Occidental, Aramco (owner-operators); Asset integrity and turnaround planning teams.

---

## Traction

- POC live at **dev.theqong.com** — fully functional upload → process → CSV pipeline
- Tested on **real Occidental Mukhaizna** drawings (Oman), classified project data
- **27 valves extracted** from initial drawing; ≥90% recall validated against expert ground truth
- Full deployment pipeline: Docker, FastAPI, SQLite, auto-deploy CI/CD on Ubuntu VPS
- Built and deployed in under **2 weeks**

---

## Business Model

| Model | Price | Target |
|-------|-------|--------|
| Per-drawing | $10–50/P&ID | SME EPC firms, one-off projects |
| SaaS | $500–2,000/month per project team | Mid-size contractors |
| Enterprise | Custom annual license | Shell, BP, Aramco scale |

**Unit economics**: ~$0.10–0.50 API cost per drawing → $10–50 revenue = **20–500x gross margin**.

---

## Roadmap

```
Phase 1 (Done)    — AI wrapper POC: Claude Vision + PyMuPDF tile pipeline
Phase 2 (6 mo)    — Own CV/OCR model (YOLO + PaddleOCR) trained on proprietary data
Phase 3 (12 mo)   — Full P&ID digitization: instruments, equipment, pipelines
Phase 4 (18 mo)   — P&ID-to-digital-twin: live plant model from drawing set
```

**The moat**: Every P&ID processed becomes training data. Phase 2 replaces the Claude API with a proprietary model trained on thousands of annotated drawings — zero marginal API cost, dramatically better accuracy, impossible for competitors to replicate without the same dataset.

---

## The Ask

**Raising**: [Seed round amount]
**Use of funds**:
- 40% — Engineering (Phase 2 model development, full P&ID scope)
- 30% — Sales & customer success (land 3–5 pilot EPC customers)
- 20% — Infrastructure & compute
- 10% — Legal, IP, operations

**Milestones with this round**:
- 3 paying pilot customers within 6 months
- Own OCR/CV model in production within 9 months
- $X ARR within 12 months

---

*Qong — from drawing to data, automatically.*
