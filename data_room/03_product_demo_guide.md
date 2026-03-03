# Product Demo Guide

*For investor meetings, sales calls, and conference presentations*

---

## Setup (Do Before Every Meeting)

- [ ] Open https://dev.theqong.com in Chrome (or Brave — not Safari)
- [ ] Log in as `demo` / `Demo@2024` — **never use admin in a live demo**
- [ ] Have sample P&ID PDF ready on desktop: `INPUT-MUK-62-1-15-1004-001-24C7-D.pdf`
- [ ] Have sample output CSV ready: `docs/Output-Valve List.csv`
- [ ] Have the Loom recording URL ready (backup if internet drops)
- [ ] Zoom to 125% in browser so all text is readable on shared screen
- [ ] Close Slack, email, notifications — put phone face down

---

## Live Demo Script (3 minutes)

### Opening (15 sec)
> "Let me show you the product. This is a real P&ID from Occidental Mukhaizna in Oman — a 4,768 by 3,368 pixel scanned image. There's no text in this file, just pixels. An engineer would spend 3 hours extracting the valve list from this drawing manually."

### Upload (30 sec)
- Click **New Job** or **Upload**
- Drag the PDF onto the upload zone
- Point out: "This is a standard scanned PDF — the kind every engineering firm has millions of."
- Click **Submit / Start Extraction**

### Processing (45–60 sec)
> "While it processes — the system tiles the image into sections, sends each tile to an AI vision model that reads the symbols and labels, then reassembles the results. There's overlap between tiles so nothing at a boundary gets missed."

- Show the progress bar / job status updating in real time
- If there's a job log, click to show the stages: tiles → extraction → parsing → validation

### Results (60 sec)
- Click on the completed job
- Show the valve list on screen: tag numbers, sizes, fluid codes, piping classes
- **Key moment**: Scroll down the list — "27 valves, all structured, all readable"
- Click **Download CSV**
- Open the CSV in your spreadsheet app — it's ready to import into AVEVA, SmartPlant, or any project management tool

### Closing (15 sec)
> "3 minutes, not 3 hours. $0.50 in compute cost, not $300–400 in engineer time. And every drawing we process gets more accurate as we build our training data."

---

## Handling Questions During the Demo

**"What if the drawing is unclear?"**
> "The AI reads at high resolution — we render at 3x DPI. On low-quality scans we flag low-confidence detections for human review, rather than silently including bad data."

**"Does it work on other P&ID formats?"**
> "We've tested on Occidental Mukhaizna drawings. The prompting includes the project's legend, so it adapts to the symbol set used in that drawing package. Different projects use slightly different symbols — the legend-aware approach handles this."

**"What about instruments, not just valves?"**
> "That's Phase 3. Valves are the highest-volume, most automatable item. Once we've nailed valves we extend the same pipeline to instruments (FT, PT, LT), equipment items, and eventually full pipeline connectivity."

**"Why can't a big company just copy this?"**
> "AVEVA and Hexagon require the P&ID to be redrawn inside their authoring tools — millions in license costs and years of re-digitization. We work on legacy scanned drawings as-is. The second part of the answer is our Phase 2 roadmap: a proprietary model trained on our annotated dataset. The data moat compounds with every drawing processed."

---

## Backup Plan (If Internet Fails)

1. **Loom recording**: [URL of 3-min screen recording of full demo flow]
2. **Static screenshots**: Show in sequence — upload screen → processing → results → CSV download
3. **Pre-generated output**: Open `docs/Output-Valve List.csv` directly and walk through the columns

---

## Demo Account Details

| Field | Value |
|-------|-------|
| URL | https://dev.theqong.com |
| Username | demo |
| Password | Demo@2024 |
| Sample P&ID | INPUT-MUK-62-1-15-1004-001-24C7-D.pdf |

> **Note**: Reset the demo job history before each meeting so investors see a clean slate. If job history from previous runs is visible, that's fine — it shows real usage.

---

## Files to Have Ready (on Desktop)

```
~/Desktop/demo/
├── INPUT-MUK-62-1-15-1004-001-24C7-D.pdf   ← upload this live
├── Output-Valve List.csv                     ← show as "expected output"
├── demo_backup.mp4                           ← Loom export, backup only
└── demo_screenshots/                         ← last resort backup
    ├── 01_upload.png
    ├── 02_processing.png
    ├── 03_results.png
    └── 04_csv_download.png
```
