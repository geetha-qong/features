# QONG Systems — Design System

> AI-Powered Engineering Intelligence for Oil & Gas — FEED & EPC.
> **Beyond Plant.**

---

## What QONG is

QONG Systems is a Next-Engineered platform for the Oil & Gas energy sector. Its core engine reads **P&ID** drawings with computer vision + structured AI and auto-generates the dependent engineering deliverables — **Instrument Index, Instrument Datasheets, Control Narrative, Cause & Effect, I/O Lists, Valve Lists** — that today are maintained by hand and constantly drift out of sync.

The flagship hardware product is **QONG BOX**: an on-premises, air-gapped appliance that runs the full AI stack locally. P&IDs and deliverables never leave the plant boundary — built for NDA-bound FEED packages, classified projects, and clients with hard data-sovereignty requirements.

**Operated by:** INNOARTHI PRIVATE LIMITED · CIN U77309KA2025PTC202654
**Site:** https://qongsystems.com
**Socials:** @QongSystems on X, YouTube, LinkedIn, Instagram

### Products / surfaces represented in this system
1. **Marketing website** (qongsystems.com) — Home, About, Product, Technology, Careers, Contact. Light theme, gradient brand accents over white + industrial photography.
2. **QONG Drive** (product surface) — the in-app P&ID intelligence dashboard. Dark theme, mono engineering tags, live extraction states. *Not yet shipping publicly; recreated here from the product-page mockup on qongsystems.com.*
3. **QONG BOX** — hardware appliance. Visual treatment is a dark rack-unit illustration with status lamps.

### Source materials used to build this system
- `uploads/Q_Qong_only.png` — the Q monogram (2000×2000 PNG, transparent) — copied to `assets/qong-mark.png`.
- `uploads/QONG LOGO(1).jpg` — the QONG wordmark + "BEYOND PLANT" lockup — copied to `assets/qong-wordmark.jpg`.
- **qongsystems.com** — Home, Product, Technology pages fetched as the canonical source for copy, structure, and visual motifs. No codebase / Figma was provided; visuals are inferred from page structure + the marketing site's iconography choices.

---

## File index

| File / Folder | What it is |
| --- | --- |
| `README.md` | This file — full guide. |
| `colors_and_type.css` | All CSS variables: brand colors, neutrals, semantic, type scale, spacing, radii, shadows, motion. Drop-in. |
| `SKILL.md` | Agent-Skill manifest so this system works in Claude Code too. |
| `assets/` | Logos (mark + wordmark), exported icon SVGs. |
| `fonts/` | Brand fonts: **Outfit** (variable) and **Barlow Condensed** (400/600/700/800/900). JetBrains Mono is loaded from Google Fonts CDN (engineering tags only). |
| `preview/` | Specimen cards rendered in the Design System tab. |
| `ui_kits/marketing-site/` | High-fidelity recreation of the qongsystems.com marketing site with reusable JSX components. |

---

## CONTENT FUNDAMENTALS

### Voice
QONG writes like a **senior engineer pitching to other senior engineers**. Confident, technical, plain. The product solves a real, painful, expensive problem (manual P&ID-to-deliverable transcription, R5 revision cycles) and the copy never apologises for being technical.

- **POV:** Mostly third-person product voice ("QONG reads…", "QONG generates…"). Occasionally "we" when the company speaks ("We don't just draw — we standardize."). Almost never "you" in body copy, but "you" appears in CTAs and direct-address moments ("Ready to Go Beyond Plant?").
- **Tense:** Present, active. "Reads", "generates", "validates". Never future-conditional ("would", "could").
- **Mood:** Decisive. Outcomes are stated as facts, not promises.

### Casing
- **Hero / page titles:** Title Case with extra-wide letter-spacing on key wordmarks. The hero literally renders as `QONG  BEYOND  PLANT` with double-spaces between words to enforce the lockup feel.
- **Section labels (overlines):** ALL CAPS, ~16% tracking. Examples: `NEXT-ENGINEERED FOR OIL & GAS`, `OUR FLAGSHIP PRODUCT`, `THE PROBLEM`, `WHY CHOOSE QONG`.
- **Section headlines:** Title Case, often with a soft double-space mid-headline as a visual break (`Redefining  Engineering Intelligence`).
- **Body sentences:** Sentence case.
- **Engineering tags:** ALL CAPS mono (`PT-101`, `FT-201`, `LT-301`, `V-102`). Always hyphenated, always with a leading discipline code.

### Spelling & idiom
**British English.** "Digitised", "standardise", "optimise", "analyse", "behaviour". A noticeable South-African / Commonwealth touch ("R5 revisions" — i.e. Revision 5) without slang. Acronyms are heavy and unapologetic: FEED, EPC, P&ID, I/O, ISA, IEC, CV, OCR, EKG, SLM. First use is occasionally expanded but mostly assumed.

### Punctuation tics
- **Em-dashes everywhere** — used to extend a thought rather than parenthetical commas. Examples: "QONG is a Next-Engineered solution — designed to bridge the gap…", "no cloud, no internet, no compromise".
- **Triplets / three-beat patterns** — "Encrypted · Offline · Air-gapped", "Encrypted · Air-Gapped · On-Premises", "faster, safer, and more consistent".
- **Middle dots** (`·`) separate hardware status chips and metadata.
- **Plus-signs** in feature lists: "Cross Disciplinary Intelligence", "AI Powered P&ID Interpretation".
- **"+"** rather than "and" in lists of disciplines: "Mechanical + Electrical + Instrumentation".

### Specific examples (lift these patterns directly)

| Pattern | Example from site |
| --- | --- |
| Hero overline | `Next-Engineered for Oil & Gas` |
| Hero headline | `QONG  BEYOND  PLANT` |
| Hero sub | `AI-Powered Engineering Intelligence` |
| Section overline | `THE PROBLEM` / `THE PROCESS` / `WHY CHOOSE QONG` |
| Section headline | `Redefining  Engineering Intelligence` |
| Feature header | `AI-Powered P&ID Reading` |
| Hardware spec line | `ENCRYPTED · OFFLINE · AIR-GAPPED` |
| Status chip | `Now in Active Development` |
| CTA primary | `Request Early Access` / `Request Demo` |
| CTA secondary | `Explore Platform` / `See How It Works` |
| Closing | `Ready to Go Beyond Plant?` |

### Emoji?
The live website **does use emoji** as feature-card icons (🧠 ⚡ 📋 📄 🚫 🔗 💸 👁 🧬 ⚖ 🔮). It reads as a v1 / pre-launch shortcut — the rest of the site is otherwise polished engineering-minimal. **For new work, prefer real line icons (Lucide)** and keep emoji as a fallback only where a quick prototype is needed. This system ships both: the live-site emoji set is preserved in the Components cards as `Emoji Feature Tile`, and a Lucide-based equivalent is shipped as the recommended replacement.

### What QONG does NOT do in copy
- No exclamation marks. The tone is engineer-cool.
- No second-person hype ("You'll love…").
- No vague verbs ("leverage", "empower", "unlock potential"). Verbs are concrete: reads, extracts, validates, generates, propagates, structures.
- No filler stats or made-up percentages.

---

## VISUAL FOUNDATIONS

### Colors

The brand's defining device is the **wordmark gradient**: a left-to-right ramp from electric indigo → mid-purple → magenta. Every gradient in the system is a tighter or looser variation of this one ramp; no other hues belong to the brand.

| Token | Hex | Use |
| --- | --- | --- |
| `--qong-blue` | `#2E3FBE` | Left edge of gradient — Q stem |
| `--qong-indigo` | `#5347CC` | Quarter point — O |
| `--qong-purple` | `#8B3FCE` | Midpoint — N — **primary brand color for links, buttons, accents** |
| `--qong-magenta` | `#C73FBE` | Right edge — G |
| `--ink-1000…--ink-50` | true-black → near-white | Industrial neutral ramp |
| `--ok / --warn / --error / --info` | greens / amber / red / blue | Engineering status |
| `--scan-cyan` | `#22D3EE` | Live-extraction highlight in the product UI |

**Light** is the marketing default — clean white surfaces with the gradient appearing only as accents (a vertical bar at the start of a section heading, a button fill, a gradient text on the lockup, a soft `--qong-gradient-soft` wash behind a card).

**Dark** is the product / hardware variant — `--ink-1000` and `--ink-900` for chrome with the same gradient pulled forward as glow and brand thread.

### Type

- **Body + UI + Display:** **Outfit** (variable font, one `outfit.woff2` covering 100–900). Geometric sans with a wide aperture — used for everything except impact lockups, overlines, and engineering tags.
- **Impact + Overline + Hero lockup:** **Barlow Condensed** (400 / 600 / 700 / 800 / 900). The condensed proportions give the QONG wordmark its characteristic vertical compression. The hero `QONG BEYOND PLANT` lockup, ALL-CAPS section overlines, and the QONG BOX wordmark on the hardware tile all use Barlow Condensed.
- **Mono:** JetBrains Mono — 400/500/700 — used exclusively for **engineering tags** (`PT-101`), data labels, code, status chips, dimensions.

The display scale follows a 1.250 ratio, tightened at the top (`clamp(56px, 8.5vw, 112px)` for hero impact). Letter-spacing is set tight (`-0.005em` on heavy condensed; `-0.02em` on Outfit display sizes) and stretched (`+0.16em`) on overlines — that ALL-CAPS-with-wide-tracking treatment is one of the brand's strongest identifiers (`BEYOND PLANT`, `NEXT-ENGINEERED FOR OIL & GAS`).

### Spacing & layout
- **4-px base grid.** Tokens `--s-1` (4 px) through `--s-12` (120 px).
- **Container width** 1200 px max; narrow container 880 px for dense text.
- **Section rhythm** on marketing: `--s-12` top/bottom padding between sections, `--s-9` between heading and body, `--s-6` between body and CTA.
- **Card padding** is generous: `--s-6` to `--s-7` interior; cards never feel cramped because the system trusts whitespace to do the heavy lifting.

### Backgrounds
- **Default:** plain white (`--ink-0`).
- **Soft wash:** `--qong-gradient-soft` (lavender → magenta-pink, ~6% saturation) behind feature sections.
- **Industrial photography:** dark moody hero shots (refinery at night, offshore platform). Used full-bleed at the top of pages with a `--ink-1000` overlay at 55–70% opacity so the gradient text and white type stay legible.
- **No repeating patterns, no textures, no hand-drawn illustrations.** The brand is engineering-tech, not retro / craft.

### Borders & corners
- **Default radius:** 12 px (`--r-3`) for cards, 8 px (`--r-2`) for form fields, 16/24 px (`--r-4`/`--r-5`) for feature cards.
- **Pills** (`--r-pill`) for status chips, tags, and the "Now in Active Development" indicator (with a small `●` glyph in `--qong-purple` preceding the label).
- **Border weight is always 1 px.** No heavy outlines anywhere.
- **Color:** hairline `--border` (#DCDFEA on light). On dark, `--ink-700` (#2A2E4A).

### Shadows / elevation
A 5-step scale (`--shadow-xs` → `--shadow-xl`). Marketing uses mostly `--shadow-sm` for cards at rest, `--shadow-md` on hover. **Brand glow** (`--glow-brand`, a purple drop-shadow) is reserved for primary CTAs and the live-extraction highlight in the product UI.

### Animation
- **Easing:** custom `--ease-out` (`cubic-bezier(0.16, 1, 0.3, 1)`) for entrances, `--ease-std` for state changes. No bounces, no springs — the brand is precise.
- **Durations:** `120ms` (hover), `200ms` (state), `320ms` (entrance), `560ms` (page transitions).
- **Hover state:** primary buttons brighten + lift `translateY(-1px)` + grow the brand glow. Secondary buttons darken their border. **Never** flash a hue change.
- **Press state:** `translateY(0)` + glow shrinks. No shrinking-the-whole-element treatment.
- **Scroll-driven motion** on marketing — fade-up by 16 px over 320 ms, staggered by 60 ms per item.

### Transparency & blur
Used sparingly:
- Hero photo overlays (`rgba(10, 11, 20, 0.6)`).
- The cookie banner / sticky nav uses `backdrop-filter: blur(12px)` over a semi-transparent surface.
- Status chips on dark photography use `rgba(255,255,255,0.08)` with `backdrop-filter: blur(8px)`.

### Imagery vibe
Cool, slightly desaturated industrial photography — oil rigs, refineries at night, offshore platforms. **Never warm.** Color temperature pushed toward the cyan/blue side; a deep `--ink-1000` overlay tames anything too photographic.

### Cards
- 1 px hairline border (`--border`).
- 12 px radius default.
- `--shadow-sm` at rest, `--shadow-md` on hover, lift `-2 px`.
- Optional **gradient top border** (3 px tall `--qong-gradient` slice) on feature/highlight cards — a recurring motif in the QONG layout that lets a card declare its importance without changing color.
- No "rounded card with only a left-color accent" treatment. Avoid.

### Layout rules
- **Sticky nav** on scroll, white with `backdrop-filter: blur(12px)` and a hairline bottom border.
- **Fixed CTA** sometimes appears bottom-right on long product pages.
- **No carousels.** Comparisons / sectors / pillars are always shown as a grid.

---

## ICONOGRAPHY

### What's in use today
The live site uses **system emoji as feature icons** (🧠 ⚡ 📋 📄 🚫 🔗 💸 👁 🧬 ⚖ 🔮). It's visually inconsistent (emojis render differently across OS) and reads as a placeholder.

### What this design system ships
**Lucide** — clean 1.5 px stroked line icons, MIT licensed, served from CDN. Lucide's geometric, evenly-weighted style fits QONG's engineering tone far better than emoji and matches the "Plus Jakarta Sans" character (precise, modern, neutral). Wherever the live site uses an emoji, this design system maps it to a Lucide equivalent — see `preview/icons-mapping.html` for the full table.

**Use icons at 20 / 24 / 32 / 40 px** with stroke `1.5`, color matching surrounding text (`currentColor`). For brand-tinted icons inside feature tiles, use `--qong-purple`. Never colour-fill the icon glyph itself.

> **Substitution flag.** Lucide is a substitution for whatever the QONG team is using today (which is OS-rendered emoji). If you have a custom icon set, drop SVGs into `assets/icons/` and the components will resolve them locally before falling back to Lucide.

### CDN
```html
<script src="https://unpkg.com/lucide@latest"></script>
<script>lucide.createIcons();</script>
```

### Mapping (live emoji → Lucide)
| Live | Lucide | Where |
| --- | --- | --- |
| 🧠 | `brain` / `cpu` | "AI-Powered P&ID Reading" |
| ⚡ | `zap` | "Unified Cross-Discipline Platform" |
| 📋 | `clipboard-list` | "Auto-Generated Deliverables" |
| 📄 | `file-text` | "Manual Documentation Overload" |
| 🚫 | `ban` | "No Intelligent Tools" |
| 🔗 | `link-2` | "Change/Error Cascade" |
| 💸 | `trending-down` / `banknote` | "High Revisions = High Costs" |
| 👁 | `eye` / `scan-search` | "Intelligent Drawing" |
| 🧬 | `git-branch` / `network` | "Structured Engineering" |
| ⚖ | `scale` / `gavel` | "Compliance & Standards" |
| 🔮 | `radar` / `layers` | "2D Twin Layer" |
| 📊 / 📑 / 🔀 / 📋 | `bar-chart-3` / `file-spreadsheet` / `git-merge` / `list-checks` | Deliverable cards |

### Logos available
- `assets/qong-mark.png` — Q monogram on transparent background. Use at any size ≥ 64 px.
- `assets/qong-wordmark.jpg` — full "QONG / BEYOND PLANT" lockup. **Has a white background — request a transparent PNG/SVG from the brand owner for product use.**
- A code-rendered `<QongMark>` SVG component is provided in the UI kit if you need a scalable, recolorable version.

### Unicode glyphs commonly used
- `●` filled circle — status indicator (`● Now in Active Development`)
- `·` middle dot — separator (`Encrypted · Offline · Air-gapped`)
- `↓` down arrow — flow diagrams (input → process → output)
- `▸` right triangle — bullet replacement in feature lists
- `—` em dash — *liberally* (the brand's single most identifiable punctuation tic)

---

## How to use this system

```html
<link rel="stylesheet" href="colors_and_type.css">
```

Then either lean on the element defaults (`<h1>`, `<p>`, `.overline`, `.tag`, `.display-xl`, `.text-gradient`) or pull individual tokens (`color: var(--qong-purple)`).

For the dark product UI, add `data-theme="dark"` on `<body>` or `<html>`.

---

## Caveats & known gaps

1. **No codebase, no Figma.** Everything in this system is reverse-engineered from the public marketing site + the supplied logos. If the team has internal Figma libraries, please link them.
2. ~~Display font is substituted.~~ **Resolved** — Outfit + Barlow Condensed brand fonts are installed in `fonts/`.
3. **Wordmark asset has a white background.** A transparent PNG/SVG is needed for product UI work.
4. **Product UI (QONG Drive) is recreated from a single illustrative mockup on the product page** — not from a real deployed app. Once the product surfaces real screens, the UI kit will need a pass.
5. **Iconography is a Lucide substitution** for the live site's emoji set. If a custom icon set exists, drop into `assets/icons/`.

---

## Asking for what we need next

To make this system production-grade, please share:
- The display font file (or commercial license info)
- A transparent / vector version of the wordmark + Q mark
- Any internal Figma library or design tokens file
- Screenshots / a build of QONG Drive (the product UI)
- A full sentence list of any brand-vocabulary "always / never" rules
