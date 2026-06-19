<sub>`// GEMACH ECOSYSTEM · BRAND`</sub>

# Branding — Gclaw / Gemach

Gclaw is a product in the **Gemach** ecosystem and carries the Gemach visual
identity: dark, premium, sharp, technical. A geometric lion mark in clean **Inter**
type on rich black. The tone is confident and security-credibility-first — never
loud hype.

The full brand system is the `gemach-brand` Claude Code skill. This file is the
short, in-repo reference so docs and release notes stay on-brand without it.

## Assets (committed)

`assets/brand/` holds what the docs reference:

| file | use |
|---|---|
| `gemach-lockup-white-on-dark.png` | primary lockup, dark backgrounds (README header) |
| `gemach-lockup-black-on-light.png` | lockup for light backgrounds (theme fallback) |
| `gemach-lion-white.svg` / `gemach-lion.svg` | the geometric mark (master recolors via `currentColor`) |
| `gemach-lion-gfund-emerald.svg` | emerald mark (GMAC/life-energy accent, README footer) |

Logo rules: never stretch, rotate, or add shadows; keep the knocked-out face
transparent; light mark on dark, dark mark on light; min size ~24–32px.

## Color tokens

```css
--rich-black: #060A17;  /* primary background */
--gem-white:  #FFFFFF;  /* headlines */
--gbot-red:        #DF2E2E;  /* alert / breaker accent */
--gloans-blue:     #61B8FF;  /* identity / Base accent */
--gvaults-purple:  #704FF6;  /* evolution accent */
--gfund-emerald:   #49B875;  /* GMAC / life-energy / "verify" accent */
/* navy → silver ramp for panels, borders, secondary text */
--navy-700: #162139;  --slate-400: #697083;  --silver-200: #D5D9E1;
```

Accents are accents — one mark, link, badge, or highlight. Never large flat fills
of an accent color. Default surface is rich-black with white headlines and the
silver ramp for everything secondary.

## Typography & motif

- **Inter** only. Bold, often ALL-CAPS headlines; Regular silver/white body.
- The **`//` prefix** is the signature motif. Eyebrow labels and section headers
  use it: `// QUICK START`, `//GEMACH`, `// GEMACH ECOSYSTEM · ONCHAIN`.
- Markdown can't set fonts/background, so docs carry the brand through the lockup,
  the `//` motif, brand-color badges (`labelColor=060A17`), and the voice.

## Release-notes format

Lead every GitHub release body with the eyebrow + a one-line what-it-is, then the
substance. Plain, factual language — no "critical/comprehensive/robust" inflation.

```markdown
`// GEMACH · GCLAW`

**One line on what shipped and why it matters.**

- bullet of substance
- bullet of substance

Verified: <what was actually checked>.
```
