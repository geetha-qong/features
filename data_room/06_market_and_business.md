# Market & Business Model

---

## The Market

### Problem Scale

Oil & gas is the world's most drawing-intensive industry. Every facility is documented in P&IDs — there are no exceptions. By regulation (OSHA 1910.119, ATEX, IEC 61511), every plant must maintain current, accurate P&IDs for process safety management.

**Key numbers**:
- ~500,000 active oil & gas, petrochemical, and LNG facilities globally
- Average facility: 200–5,000 P&ID drawings in the drawing set
- Drawing sets are updated continuously throughout plant life (30–40 years)
- Each drawing update requires re-extraction of valve lists

**The extraction problem recurs every time**:
- A new project is built (greenfield/brownfield)
- A drawing is revised
- A plant turnaround is planned (requires up-to-date valve list for procurement)
- An asset changes hands (new owner needs to digitize legacy drawings)

### Market Size

| Level | Scope | Value |
|-------|-------|-------|
| **TAM** | Global P&ID software, plant digitization, and engineering data management | ~$3.2B (2025), growing 8% CAGR |
| **SAM** | Valve list and instrument index extraction from P&IDs — EPC + owner-operator segment | ~$800M |
| **SOM** | Top 100 EPC firms + top 50 owner-operators, per-project extraction fees | ~$40–80M/year |

**SOM calculation**:
- 100 EPC firms × 20 active projects/year = 2,000 projects
- Average 300 P&IDs per project × $25/P&ID = $7,500/project
- = **$15M/year from EPC segment alone**
- Owner-operators run turnarounds every 3–5 years on 200–500 P&IDs = additional $30M+

---

## Target Customers

### Primary: EPC Contractors

**Who they are**: Engineering, Procurement & Construction firms that design and build oil & gas facilities. They produce P&IDs during design and must extract valve/instrument data for procurement, construction, and handover.

**Top targets**:
- Worley (Australia/global, $10B+ revenue)
- Wood PLC (UK/global, $6B+ revenue)
- Petrofac (UAE/UK)
- Jacobs Engineering
- Technip Energies
- McDermott International
- KBR Inc.
- Saipem

**Buyer persona**: Lead Piping Engineer, Project Document Controller, or Engineering Manager
**Pain point**: Must produce valve lists for procurement in weeks — manual process takes months
**Budget**: Project-level spend, usually < $50K/project approval threshold

### Secondary: Owner-Operators

**Who they are**: Oil companies and national oil companies that own and operate the facilities. They need valve lists for:
- Asset integrity programs
- Turnaround (shutdown/maintenance) planning
- Digital twin initiatives
- Regulatory compliance (PSM, ATEX)

**Top targets**:
- Shell, BP, TotalEnergies, ExxonMobil
- Aramco (Saudi Arabia) — world's largest oil company
- ADNOC (UAE)
- Occidental (current POC is on their Mukhaizna drawings)
- Petrobras (Brazil)
- National Grid / utilities (expanding beyond oil & gas)

**Buyer persona**: Asset Integrity Manager, Digital Transformation Lead, Turnaround Planner
**Pain point**: Legacy drawing sets with zero structured data — must digitize to run any digital program
**Budget**: Capex or digital transformation budget, often > $100K/project

### Tertiary: Document Management Vendors

Companies like Aveva, Hexagon, Bentley, and AVEVA partner with engineering data vendors to provide structured P&ID data as a service. A white-label or API arrangement with one of these is a potential exit path.

---

## Business Model

### Revenue Streams

**1. Per-Drawing (Transactional)**
- Price: $10–50 per P&ID
- Best for: SME EPC firms, one-off projects, evaluation
- No contract needed — credit card / invoice
- Low friction to start

**2. SaaS Subscription (Recurring)**
- Price: $500–2,000/month per project team (unlimited drawings within plan)
- Best for: EPC contractors with ongoing project flow
- Billed monthly or annually
- Upsell path: team seats, API access, priority processing

**3. Enterprise License (Annual)**
- Price: $50K–200K/year
- Best for: Owner-operators digitizing large drawing sets
- Includes: unlimited drawings, dedicated support, SLA guarantees, on-premise option
- Long sales cycle (6–12 months) but high contract value

### Pricing Rationale

| Model | Our Price | Manual Alternative | Value Multiple |
|-------|-----------|-------------------|----------------|
| Per-drawing | $25 | $300–400 (3hr × $100/hr) | 12–16x cheaper |
| Monthly SaaS | $1,000/month | 10 drawings/month × $300 = $3,000 | 3x cheaper |
| Enterprise | $100K/year | 500 drawings × $300 = $150,000 | 1.5x cheaper |

Even at enterprise pricing, Qong is significantly cheaper than the manual alternative. The sell is not price — it's speed (3 min vs 3 hours) and availability (no engineer scheduling required).

---

## Go-To-Market Strategy

### Phase 1 — POC to Pilot (0–6 months)

**Goal**: 3–5 paying pilot customers

**Tactics**:
- Direct outreach to piping engineers on LinkedIn (they are the end users, not procurement)
- Conference presence: ADIPEC, OTC, AVEVA World
- Content marketing: "How to automate P&ID valve list extraction" technical blog posts
- Use Occidental Mukhaizna POC as social proof — request a testimonial / case study

**Qualification criteria for pilots**:
- Active project with ≥ 100 P&IDs in 3 months
- Technical champion (piping engineer) who will test and validate output
- Willing to share feedback and be referenced (anonymously acceptable)

### Phase 2 — Land & Expand (6–18 months)

**Goal**: 10–20 active customers, $500K ARR

**Tactics**:
- Each successful pilot project becomes the reference for the next EPC at the same firm
- EPC firms run 20+ projects/year — land one project team, expand to the firm
- Owner-operator customers have 200–5,000 drawings — one deal is a large contract
- Partner with drawing management platforms (Proarc, AVEVA, Bluebeam) as a plug-in

### Phase 3 — Market Leadership (18–36 months)

**Goal**: Dominant position in P&ID valve/instrument extraction, $5M ARR

**Tactics**:
- Proprietary model (Phase 2) provides accuracy and cost advantages no competitor can match
- Expand scope to instrument index (same pipeline, different target symbols)
- Full P&ID digitization offering (equipment, pipelines, connectivity)
- Pursue integration with ERP systems (SAP PM, IBM Maximo) for maintenance workflows

---

## Competitive Analysis

### Direct Competitors

**None currently.** There is no commercial product that extracts structured data from scanned P&IDs at this price point and without requiring re-authoring.

### Indirect Competitors / Adjacent Threats

| Competitor | Approach | Why We Win |
|------------|----------|-----------|
| **Manual process** (status quo) | Engineers with Excel | 10–100x faster, 80% cheaper |
| **AVEVA E3D / SmartPlant P&ID** | Re-author drawings in software | Requires $500K+ license + redraw of all P&IDs — we work on existing scans |
| **Hexagon (PPM)** | Enterprise P&ID management | Same as AVEVA — structured authoring, not scan reading |
| **General OCR tools** (ABBYY, etc.) | Extract raw text from PDF | Cannot understand P&ID notation, symbols, or spatial relationships |
| **Intern/offshore extraction** | Manual, offshore cost reduction | Still 3–4 hrs/drawing at $30–50/hr = $90–200/drawing — we're still 5–10x cheaper |
| **New AI entrant** | Wrap same Claude API | Can replicate the API call. Cannot replicate Phase 2 proprietary dataset. |

### The Defensibility Argument

The question VCs always ask: "Why can't someone just copy you?"

**Short answer**: Phase 1 (AI wrapper) can be copied. Phase 2 cannot.

Phase 2 trains a proprietary YOLO model on our annotated P&ID dataset. That dataset:
- Is built from hundreds of real client drawings (proprietary)
- Requires domain expertise to annotate correctly (not crowdsourceable)
- Takes 6–12 months to accumulate sufficient examples
- Compounds with every new drawing we process

A new entrant starting today would need 12–18 months and real client partnerships to collect the same data. By then we will have processed thousands of drawings and will be 95%+ accurate with near-zero API cost. The data flywheel is the moat.

---

## Financial Projections (Illustrative)

### Year 1 (Post-Raise)

| Quarter | Customers | Avg Rev/Customer | MRR | ARR Run Rate |
|---------|-----------|-----------------|-----|--------------|
| Q1 | 2 pilots (free) | $0 | $0 | $0 |
| Q2 | 5 paying | $500/mo | $2,500 | $30K |
| Q3 | 12 paying | $750/mo | $9,000 | $108K |
| Q4 | 20 paying | $1,000/mo | $20,000 | $240K |

### Year 2

| Scenario | Customers | Avg ARR/Customer | Total ARR |
|----------|-----------|-----------------|-----------|
| Conservative | 30 | $12,000 | $360K |
| Base | 60 | $15,000 | $900K |
| Optimistic | 100 | $20,000 | $2M |

### Unit Economics at Scale (Year 2+, Own Model)

| Metric | Value |
|--------|-------|
| Gross margin | 92–95% |
| CAC (direct outreach + conferences) | ~$2,000–5,000 |
| LTV (SaaS, 24-month avg) | $24,000–36,000 |
| LTV:CAC ratio | 5–18x |

---

## Use of Funds ($[X]M Seed Round)

| Category | % | Use |
|----------|---|-----|
| Engineering | 40% | Phase 2 model development, full P&ID scope |
| Sales & Customer Success | 30% | First sales hire, pilot customer onboarding |
| Infrastructure & Compute | 20% | GPU training, production scaling |
| Legal, IP, Operations | 10% | IP filings, TOS/privacy, company ops |
