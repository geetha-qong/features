# QONG marketing-site UI kit

High-fidelity React recreation of qongsystems.com (Home + Product + Technology sections distilled).

## What's here

| File | What it is |
| --- | --- |
| `index.html` | Mounts every component in marketing order. **Open this for the demo.** |
| `Nav.jsx` | Sticky pill nav with backdrop blur. |
| `Hero.jsx` | Full-bleed hero — overline + `QONG BEYOND PLANT` gradient lockup + CTA pair + Drive preview. |
| `Sections.jsx` | About, Features grid, Problem grid, Process flow, Why choose Qong, FAQ. |
| `Drive.jsx` | Inline P&ID-intelligence mockup with extraction states. |
| `QongBox.jsx` | Hardware illustration tile (used on the technology section). |
| `Footer.jsx` | Footer + newsletter capture. |

## Notes

- All visual tokens come from `../../colors_and_type.css` — never hard-code hexes inside components.
- The page is a click-through demo: nav links scroll, hovers animate, the CTA shows a toast (no backend). It is NOT production code; cosmetic only.
- Icons are Lucide (`https://unpkg.com/lucide@latest`) — flagged substitution for the live site's emoji set.
- The QONG Drive mockup (`Drive.jsx`) is recreated from the static illustration on the live product page. Once a real product UI exists, replace this component.
