---
name: qong-design
description: Use this skill to generate well-branded interfaces and assets for QONG Systems, either for production or throwaway prototypes/mocks/etc. QONG is an AI-powered engineering platform for Oil & Gas FEED/EPC — it reads P&ID drawings and auto-generates engineering deliverables. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `README.md` file within this skill first — it contains the full content fundamentals, visual foundations, and iconography rules. Then explore the other available files (`colors_and_type.css`, `assets/`, `ui_kits/`, `preview/`).

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

Key brand facts you should always honor:
- **Brand is QONG Systems** — tagline "Beyond Plant" — Next-Engineered for Oil & Gas. Operated by INNOARTHI Private Limited.
- **Voice is technical and confident** — senior engineer talking to senior engineers. British English. Heavy em-dashes. Triplet patterns. No exclamation marks, no hype verbs.
- **Single brand gradient** — `linear-gradient(90deg, #2E3FBE 0%, #8B3FCE 50%, #C73FBE 100%)` (blue → purple → magenta). Every gradient in the system is a variation of this one.
- **Primary brand color is `--qong-purple` (#8B3FCE)** for links, buttons, accents. The full gradient is reserved for hero lockups, signature accents, and the wordmark.
- **Type: Plus Jakarta Sans + JetBrains Mono** (mono used exclusively for engineering tags like `PT-101`).
- **Iconography: Lucide line icons** (the live site uses emoji as a placeholder — prefer Lucide).
- **Light theme for marketing, dark theme (`data-theme="dark"`) for the product UI / QONG BOX**.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions about scope and target product surface (marketing site vs product UI vs sales deck vs hardware datasheet), and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need.
