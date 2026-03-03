# Pre-Meeting Checklist

*Complete this before any investor meeting or demo.*

---

## Data Room Setup

- [ ] Upload all files from `data_room/` to Google Drive / Docsend / Notion
- [ ] Set sharing permissions: link access, viewer only
- [ ] Test the link from a different browser / incognito window
- [ ] If using Docsend: enable NDA gate and page-view analytics

**Recommended folder structure on Drive**:
```
Qong Data Room/
├── 1. Executive Summary.pdf
├── 2. Pitch Deck.pdf
├── 3. Product Demo Guide.pdf
├── 4. Accuracy Report.pdf
├── 5. Technical Overview.pdf
├── 6. Market & Business Model.pdf
└── 7. Sample Output - Valve List.csv
```

---

## Product / Demo

- [ ] Create demo user: `demo / Demo@2024` on dev.theqong.com
- [ ] Test the full flow: upload → process → download CSV (do it yourself right before meeting)
- [ ] Clear any old jobs from demo account so investor sees a clean slate
- [ ] Have sample P&ID on desktop: `INPUT-MUK-62-1-15-1004-001-24C7-D.pdf`
- [ ] Have sample output CSV on desktop: `Output-Valve List.csv`
- [ ] Record a Loom backup video (3 min, full flow) — upload to a reliable URL
- [ ] Test the Loom video loads on meeting machine

---

## Accuracy / Proof

- [ ] Run the second drawing (`MUK-62-1-15-1005-001-24C7-D.pdf`) through the pipeline
- [ ] Record: drawing name, valve count found, manual count, recall %
- [ ] Add results to `04_accuracy_report.md` before sharing data room

---

## Tech Check (Day Before Meeting)

- [ ] VPS is up: `curl https://dev.theqong.com/login` returns 200
- [ ] API key has sufficient credits (check OpenRouter / Anthropic dashboard)
- [ ] No pending Docker restart or migration needed
- [ ] SSL cert valid (check in browser address bar)

---

## Meeting Setup

- [ ] Zoom to 125% in browser for readability on screen share
- [ ] Close: Slack, email, all notifications
- [ ] Phone: face down, silent
- [ ] Have data room URL copied and ready to paste in chat
- [ ] Have Loom backup URL ready (in case internet drops mid-demo)
- [ ] Practice the 3-minute demo script at least once

---

## Key Numbers to Have Memorized

| Fact | Value |
|------|-------|
| Processing time per P&ID | < 3 minutes |
| Manual alternative | 3–4 hours |
| Recall accuracy | ≥ 90% |
| API cost per P&ID | ~$0.10–0.25 |
| Price per drawing (proposed) | $10–50 |
| Gross margin | 80–98% |
| Infrastructure cost | ~$20/month VPS |
| Valves in test drawing | 27 |
| P&ID size | 4,768 × 3,368 px scanned image |
| Drawings per project (typical) | 500–2,000 |
| Engineer cost avoided per drawing | $300–400 |
| Cost avoided per project (1,000 drawings) | $300K–400K |

---

## Common VC Questions & Answers

**Q: Why can't a big company (Bentley, AVEVA, Hexagon) just do this?**
A: They require drawings to be redrawn inside their authoring software — millions in license costs and years of effort. We work on existing legacy scans as-is. Different product, different motion.

**Q: Why can't someone just copy your Claude API call?**
A: They can copy Phase 1. Phase 2 is our own CV model trained on proprietary annotated P&ID data — every drawing we process becomes training data. The data moat compounds and is impossible to replicate without the same drawing access and domain expertise.

**Q: How do you handle confidentiality — these are sensitive engineering drawings?**
A: Data is processed server-side, stored per-user in isolated directories. We can offer on-premise deployment for enterprise customers with strict data residency requirements. Phase 2 (own model) runs entirely on customer infrastructure if needed.

**Q: How do you get to 95%+ accuracy?**
A: Phase 2 — own YOLO model trained on our annotated dataset. Phase 1 gives us ≥90% and the labeled data to train it. Phase 2 is a 6-month engineering milestone, not a research problem.

**Q: What's your sales motion — how do you reach these engineers?**
A: Direct LinkedIn outreach to piping engineers and project document controllers. They are the daily users of valve lists — they immediately understand the pain. Conference presence at ADIPEC and OTC for the oil & gas audience.

**Q: What's the long-term vision?**
A: Valves are one column of data from a P&ID. A P&ID also contains instruments (FT, PT, LT), equipment items (vessels, pumps, heat exchangers), pipelines, and connectivity. The long-term vision is full P&ID-to-digital-twin conversion — every physical asset in a plant, extracted automatically from its engineering drawings.
