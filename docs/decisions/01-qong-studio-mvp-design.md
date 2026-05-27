# 01 — Qong Studio MVP Design (Aug '26)

**Date:** 2026-05-27
**Status:** approved (brainstorm output, awaiting implementation plan)
**Linked from:** FEATURES.md #08
**Supersedes parts of:** `docs/onboarding/ARCHITECTURE.md` §5 (phased delivery — the 9-month plan); `docs/onboarding/PROJECT_VISION.md` v1-target table
**Brainstorm transcript:** session of 2026-05-27 between Tarunkumar and Claude

---

## 1. Goal

Ship the first paying-customer version of Qong Studio by **August 2026** (14 weeks from this document's date).

This is the **commercially-defining** version of the product. After this ships:
- We have paying agency customers using the product daily
- We have an empirically-validated reviewer workflow (<15 min/sheet)
- We have a vendor side that's been seeded but not yet monetized
- We know which deliverables matter most in practice, informing FLEDGE (Oct '27) scope

This document supersedes the more general 9-month phased plan in `docs/onboarding/ARCHITECTURE.md` §5. That plan was written before the MVP scope was sharpened around an agency beachhead and the marketplace model. Read this doc first; the older plan provides background context only.

## 2. Beachhead persona and revenue model

**Beachhead customer:** P&ID digitization agencies. Small-to-mid teams (3-50 engineers) who today manually produce engineering documents from oil & gas P&IDs for EPC clients. They have the work, the daily-use feedback loop, the budget, and the bridge to large-oil customers once we've earned their trust.

**Why agencies, not big-oil or individual engineers:**
- Big-oil sales cycle is 6-12 months — incompatible with a 14-week MVP validation window.
- Individual engineers are a volume play needing hundreds of users at low ARPU — high marketing cost.
- Agencies are the **only persona** where we can ship and validate inside one quarter.

**Critical implication:** agencies are user-proxies for their EPC clients. Output quality must meet EPC standards from day one. Per-customer template support is a Sprint-1 problem, not a v2 polish.

**Revenue model:**
- **Primary in MVP:** Customer SaaS via P&ID digitization agencies. No Stripe / billing infra. Free for first 10-15 design-partner agencies through Aug '26; manual PDF-invoice + bank transfer for any paid signup beyond that. Stripe lands in v1.5 (Q4 '26 / Q1 '27).
- **Secondary in MVP:** Vendor onboarding ("Level 2" — vendor login + vendor catalog management + email notification on customer-approved deliverables). No vendor payments, no in-house quote management — vendors connect with customers directly via email outside Qong. This is the seed for the v1.5 vendor revenue stream.

## 3. The four customer deliverables

These are the customer-facing outputs Qong Studio produces. All four are derived from the **internal canonical graph** (NetworkX in-process, persisted to Postgres) using **per-customer template configurations** (3-5 hardcoded EPC templates in MVP).

| # | Deliverable | Extraction approach | Vendor-data dependency | MVP risk |
|---|---|---|---|---|
| 1 | **Valve List** (CSV / XLSX) | YOLO symbol detection (already shipping) + PaddleOCR tag association | None — purely P&ID derived | Low — port existing flow |
| 2 | **Instrument Index** (CSV / XLSX) | YOLO symbol detection (already shipping for Ronesans-style) + PaddleOCR + ISA S5.1 tag prefix rules | None — purely P&ID derived | Low — extend existing flow |
| 3 | **Instrument Datasheet** (PDF) | (1) instrument detection + tag + service from P&ID; (2) calibration / range / accuracy / signal type / part number from **vendor catalog match** | **High** — empty without seeded vendor data | Medium — depends on vendor catalogs being pre-loaded |
| 4 | **Equipment List** (XLSX) | YOLO symbol detection on ~12 new equipment classes (vessels, pumps, exchangers, columns, tanks) + tag association | Optional row enrichment | Medium — annotation work to add classes |

### Output formats: no industry-standard exports

All four deliverables ship as **proprietary CSV / PDF / XLSX in per-customer templates** — Ronesans format, Ebara format, MUK format, plus 2 more captured from the first 3 paying agencies. No DEXPI 2.0 XML, no ISO-15926, no industry interchange format. See `FEATURES.md #04` for the strategic rationale (lock-in). This is reversible only on a per-customer paid-for basis after MVP.

Template definitions live as JSON files in `webapp/templates/{customer_slug}.json`, describing column order, sheet structure, fonts, headers. The generator code reads the template + internal canonical graph and produces the file. **No customer-editable template editor in MVP** — the team hardcodes templates for each design partner.

## 4. System architecture

### 4.1 Service topology

```
                        +---------------------------+
                        |   Qong Studio (React)     |
                        |   - Konva review canvas    |
                        |   - Project/job workspace  |
                        |   - Deliverable export     |
                        |   - Quote-request UI       |
                        +-------------+-------------+
                                      | HTTPS
                                      v
+---------------------------+   +-----+-----------------+   +-------------------------+
|  Laravel Vendor Portal    |<->| FastAPI (Qong)        |<->|  Python Workers         |
|  (owned by lead /         |   | - SaaS infra          |   |  - extraction pipeline  |
|   external; separate      |   | - Org/project/audit   |   |  - deliverable gen      |
|   service)                |   | - Email notifications |   |  - vendor-match scorer  |
|                           |   | - REST: /vendors API  |   +-----------+-------------+
|  Vendors log in,          |   +---------+-------------+               |
|  manage catalog,          |             |                              |
|  receive email on         |             v                              |
|  customer approval        |   +---------+-------------+                |
+-------------+-------------+   | Postgres              |<---------------+
              |                  | - jobs, orgs,         |
              | reads/writes     |   review_events,      |
              |  via Qong API    |   training_events     |
              +----------------> | - vendors, products   |
                                 |   (single source of   |
                                 |    truth)             |
                                 +-----------------------+
```

**Key boundary decisions:**
- **Vendor data lives in Qong's Postgres** as the single source of truth. The Laravel portal calls Qong's REST API (`/api/vendors/...`) for all reads and writes. This keeps both apps independently deployable and version-independent.
- The Laravel portal is **operationally owned by the lead** (Tarunkumar) or an external hire. It is not in Omprakash's queue.
- All four deliverables are generated by Python workers (not the React frontend), because PDF + XLSX generation needs server-side libraries (reportlab, openpyxl).

### 4.2 Extraction pipeline

Per `docs/onboarding/ARCHITECTURE.md` §2. Subset of stages active in MVP:

1. Ingestion (existing)
2. Preprocessing — tile via SAHI (existing)
3. Symbol detection — YOLOv11 + extend to ~12 equipment classes (Geetha)
4. Text + OCR — PaddleOCR (existing, needs improvement for datasheet text fields)
5. Association — Hungarian assignment of tag text to symbol (extend existing)
6. Graph construction — NetworkX in-process (basic; not the full topology graph yet)
7. Validation — ISA S5.1 rule checks for instrument tag prefixes
8. Review UI — Qong Studio (Omprakash)
9. Export — CSV / PDF / XLSX deliverable generators (Omprakash)

**Stages explicitly OUT of MVP** (deferred to FLEDGE per §5 below): line segmentation (Stage 4 in the older plan), direction classification, full topology graph build with line endpoints, Loop Trace deliverable.

### 4.3 Vendor-match scoring

The Datasheet deliverable depends on matching detected instruments to vendor catalog entries. In MVP this is **rule-based**, not ML:

- Match key = `(tag_prefix, size, signal_type_inferred_from_tag)` — e.g. `(PT, "1in", "4-20mA")`
- For each detected instrument, the matcher looks up vendor products with the same key and returns top-3 by manually-tuned priority weights
- If a customer-preferred-vendor is set at the project level, that vendor is boosted in scoring
- If no match, the datasheet leaves the vendor-specific fields blank with a flag for the reviewer

This is intentionally simple. ML-based matching is a v1.5 / FLEDGE topic.

### 4.4 What's IN scope for MVP

**Extraction outputs:**
1. Valve List (CSV/XLSX)
2. Instrument Index (CSV/XLSX)
3. Instrument Datasheet (PDF) — with vendor data enrichment
4. Equipment List (XLSX)

**Customer-facing product:**
- Multi-user agency organizations (3-50 users per org)
- Per-project workspace (each project = one EPC client engagement)
- P&ID upload (PDF, multi-page)
- Qong Studio review canvas (React + Konva)
- Per-customer template engine (3-5 hardcoded JSON templates)
- Deliverable export buttons
- Customer-side quote-request UI (sends email to matched vendor)
- Audit trail (Postgres-only — who reviewed which sheet, which deliverable exported, which vendor records touched)

**Vendor-facing product:**
- Separate Laravel portal (built by lead / external hire)
- Vendor login + catalog CSV upload + analytics
- Email notification when a customer approves a deliverable that used the vendor's product
- 5-10 vendor catalogs pre-loaded as seed data (Swaraj + interns)

**SaaS infrastructure:**
- Orgs, projects, role-based access control, audit table
- Email notification service
- Postgres + Redis + MinIO (existing)
- AWS-hosted (cloud, not on-prem) — agencies don't require on-prem

### 4.5 What's OUT of MVP (deferred to FLEDGE Oct '27 or v1.5)

| Deferred to | Item | Rationale |
|---|---|---|
| FLEDGE Oct '27 | Line List, Cable Schedule, Junction Box Schedule, Manuals, Cause & Effect Matrix, Control Narrative | Higher extraction cost; outside agency-MVP customer ask. |
| FLEDGE Oct '27 | Full topology graph (line segmentation + direction classification + connectivity edges) | Not needed for the 4 MVP deliverables. Will be needed for Line List + Loop Trace. |
| FLEDGE Oct '27 | Electrical-drawing detection model | Cable / JB deliverables need it. |
| Out of scope (red on slide) | Control Logic Diagrams, Loop Diagrams, Heat & Mass Balance | Not derivable from P&ID inputs. |
| v1.5 (Q4 '26 / Q1 '27) | Stripe billing | Free MVP + manual invoicing covers the first cohort. |
| v1.5 | In-house quote management + RFQ flow | Vendors connect directly with customers in MVP. |
| v1.5 | Customer-editable template editor | Hardcoded templates in MVP. Editor lands when 6th distinct EPC template requested. |
| v1.5 | Collaborative multi-reviewer workflow + reviewer-performance dashboard | Single-reviewer fine for first agency cohort. |
| v1.5 | Vendor payments + Qong revenue share | Vendor onboarding is free in MVP. |
| post-MVP | SSO / SAML / enterprise auth | Agency-MVP doesn't need; big-oil sales does. |
| post-MVP | On-prem deployment / DGX Spark target | Agency-MVP is cloud-hosted. |

## 5. Team work-streams and capacity

### 5.1 Per-person allocation (Aug '26, 14 weeks)

| Owner | Streams (FTE-weeks) | Total | Available |
|---|---|---|---|
| **Omprakash** (full-stack) | Qong Studio Konva canvas (6) · per-customer template engine (3) · deliverable generators (3) · customer-side quote-request UI (1) · vendor API integration glue (1) | 14 | 14 ✅ at cap |
| **Tarunkumar** (CTO / lead) | SaaS-infra backend: orgs / projects / audit / email notifications (5) · AWS + ops (ongoing) · Laravel vendor portal — self-build or hire external (separate stream) | partial-FT | flex |
| **Geetha** (ML data / eval) | Datasheet content extraction model (6) · Equipment YOLO classes + annotation + train (4) · eval harness + golden test set (3) | 13 | 14 ✅ 1w slack |
| **Swaraj** (ML training infra) | Training infra + AWS retraining loop (4) · pre-load 5-10 vendor catalogs (3) · Postgres schema + backend helpers (2) | 9 | 14 ✅ 5w slack |

**Bottleneck:** Omprakash, at-capacity. Everyone else has slack to absorb surprises. The capacity unlock was Tarunkumar handling Laravel vendor portal separately — without that, Omprakash was at 2.3× capacity.

### 5.2 Cross-cutting open questions per work-stream

These should be answered in the implementation-plan step:
- Omprakash: which Konva interaction patterns are reused from existing Sprint 1 work (QS-60 hello-konva) vs net-new?
- Tarunkumar: build the Laravel portal in-house or contract it? If contracting, vendor lined up by week 2?
- Geetha: PaddleOCR upgrade to PP-OCRv4 a prerequisite for datasheet content extraction, or does the existing OCR cover MVP fields?
- Swaraj: which 5-10 vendors are pre-loaded (e.g. Emerson Fisher, Yokogawa, Pentair, ABB, …)? Catalogs scraped, licensed, or hand-entered?

## 6. Phasing (lightweight, 14 weeks → Aug '26)

This is a sketch, not a sprint plan. Sprint planning happens in the implementation step.

| Weeks | Milestone |
|---|---|
| 1-2 | Sprint 1 wrap-up: Qong Studio scaffold + first hello-konva canvas (per existing QS-60). Geetha kicks off datasheet field-extraction R&D. Swaraj begins AWS burst-training plumbing (QS-52). Tarunkumar finishes AWS setup (QS-48) and stands up Laravel portal repo. |
| 3-5 | Qong Studio renders one tile with bbox editing + keyboard shortcuts. Equipment-class annotations start in LS (Geetha). First 2 vendor catalogs pre-loaded (Swaraj). Orgs / projects schemas migrated (Tarunkumar). |
| 6-8 | Equipment List deliverable working end-to-end. Per-customer template engine reads JSON + outputs Valve List & Instrument Index in 2 EPC formats. Vendor portal MVP login + catalog upload (Tarunkumar). Datasheet field extraction first pass (Geetha). |
| 9-11 | Datasheet PDF deliverable generating from internal graph + vendor catalog match. Vendor portal email notifications wired (Tarunkumar). Audit table + minimal SQL queries (Tarunkumar). First eval-harness run against 5 golden MUK drawings (Geetha). |
| 12-13 | First 3 design-partner agencies invited. End-to-end test: agency uploads P&ID → reviewer corrects in 15 min → exports 4 deliverables → vendor receives email notification. Bug-fixing pass. |
| 14 | Public-ish launch — open signup for design-partner agencies. Telemetry watching. Lead working invoices manually. |

## 7. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Omprakash blocks on UI complexity (Konva learning curve, template engine more complex than estimated) | High | Swaraj has 5w slack to absorb Postgres / backend tasks if needed; Tarunkumar can take CSV/XLSX generator code off Omprakash's plate |
| First 3 agencies have wildly different template requirements → 3 templates explode into 8 | High | Customer interviews in week 1-2 lock the 3-5 templates before Omprakash writes the engine. Hard cap: 5 templates in MVP, even if it costs a customer. |
| Laravel vendor portal slips because Tarunkumar is also doing AWS + management | High | Pre-decide week 1: in-house or contractor. If in-house and not started by week 4, swap to contractor immediately. |
| Vendor catalogs hard to source (no public catalog for Yokogawa instruments) | Medium | Hand-enter top-20 SKUs per vendor (Swaraj + interns); accept incomplete coverage in MVP. |
| Datasheet field extraction harder than the existing valve/instrument flow | Medium | Geetha de-risks in weeks 3-5 with a research spike; if blocked, datasheet deliverable ships with partial vendor data in MVP and full fields in v1.5. |
| First agencies hit edge-case drawing styles (Ronesans/Ebara look very different from MUK) | Medium | Existing API-based extractor is 93% recall and used across styles already. Use API for MVP customer flow per CLAUDE.md two-mode rule; offline detector improvements continue in parallel. |
| "MVP" expands during the 14 weeks because of customer requests | High | This document is the contract. Every "while you're at it" request goes to FEATURES.md + post-MVP backlog, not into the MVP. |

## 8. Open questions to resolve in the implementation-plan step

1. Exact list of 5-10 seed vendors (Swaraj + Tarunkumar to confirm by end of week 2)
2. Laravel portal: in-house vs contractor decision (Tarunkumar to confirm by end of week 1)
3. Hosting topology: same AWS account as the existing dev.qongsystems.com? Separate VPC? (Tarunkumar to confirm)
4. Org/role schema details: do agency users have a role hierarchy (admin / reviewer / observer), or just a flat "member" model? (Tarunkumar + Omprakash to spec)
5. PaddleOCR upgrade scope (Geetha to spec in week 1)
6. First 3 design-partner agencies — who are they, when do we start customer-development interviews? (Tarunkumar)

## 9. Cross-references

- `FEATURES.md #04` — no-DEXPI / lock-in decision
- `docs/onboarding/PROJECT_VISION.md` — north-star vision
- `docs/onboarding/ARCHITECTURE.md` — full 9-month plan (superseded by this doc for MVP scope; useful background for FLEDGE)
- `docs/onboarding/REVIEW_UI_SPEC.md` — Qong Studio review UX requirements
- `docs/onboarding/ACTIVE_LEARNING_SPEC.md` — TrainingEvent loop (mostly v1.5+)
- `docs/onboarding/REFERENCES.md` — papers + reference repos (especially Microsoft Azure-Samples as the closest Family-A reference)
- `CLAUDE.md` — two-mode rule: production extraction uses API, offline detector for training only
