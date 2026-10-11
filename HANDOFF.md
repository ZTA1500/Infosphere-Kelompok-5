# Infosphere: session handoff

Last session: 2026-10-10. Everything below is **uncommitted** on `main` (see "Git state").
Read this first, then `PRODUCT.md` (product facts).

## 1. What the owner likes (build more of this)

These are the elements the owner explicitly praised. New work should feel like them.

| Element | Where | Files |
| --- | --- | --- |
| Lobbing arrow that arcs 01 → 02 → 03 as you scroll; each number lights up with a small burst when the arrow lands | Portal, "How it works" | `static/js/landing-fx.js` (`lobbingArrow`), `static/css/landing-deco.css` (`.lob*`, `.step.lit`) |
| Map pins + Infosphere logo marks floating up behind the numbers, over a faint blueprint floor plan | Portal "In numbers", About stats | `templates/_art.html` (`floaters` macro), `landing-deco.css` (`.floaters`, `.float-*`) |
| Spec-card feature squares: small animated SVG illustration on top, then `01` label, title, text | Portal "What Infosphere does" | `_art.html` (`art` macro: `route`, `talk`, `voice`, `learn`), `landing-deco.css` (`.feature-art`, `.art-learn`) |
| 3D stack of the 4 real floor plans that reacts to the story steps: sound rings (step 1), floors pull apart (step 2), **red route** walks from the kiosk on floor 1, up the escalator beam, to the Library on floor 2 which glows red (step 3). "I love this part" | About, story section | `templates/about.html` (story markup + `storyStack` script), `landing-deco.css` ("floor stack", "red route") |
| Drifting clouds at three depths that rise as you scroll, cloud banks at section edges | Portal | `landing-fx.css` (`.sky`, `.cloud`, `.cloud-bank`), `landing-fx.js` |
| The original portal structure: 3D campus photo carousel, feature squares, 01/02/03 guide, campus photo grid | Portal | `templates/landing.html` (restored from git, then layered) |

**Pattern that works:** keep the owner's existing sections and imagery, add motion and decoration as layers (separate CSS/JS files), tie animations to real meaning (real floor plans, real coordinates, real numbers).

## 2. What the owner rejected (do not bring back)

- **Yellow/amber accents.** Single accent is the brand blue (`--amber*` tokens now hold blue values; the name is legacy).
- **Dark ink header/footer bands.** Header and footer are light, quiet bars in the page's own colours.
- **Split-flap tiles** for the clock or destination (felt like decoration). Clock is plain text.
- **Scrolling ticker/marquee footers.** Footers are static.
- **Floating character / lone microphone** in the kiosk. The guide now stands at the bottom of her panel with the mic in a bar at her feet.
- **Horizontal-scroll storytelling** with empty space on the right (About). Replaced by vertical steps + sticky 3D stack.
- **Too many boxed panels / too much moving at once** on the kiosk.
- **The dash before section labels** (`.eyebrow::before`) and **em-dashes (—) in copy.** Both read as "made by AI". Use commas, colons, full stops.
- **Invented numbers or claims** (old portal had "12,482 conversations", "94.6% resolved"). Only real data, e.g. `/api/facts`.
- **Full redesigns of pages the owner liked.** Ask before replacing structure.
- **Lag.** Owner noticed it quickly. Follow the performance rules in section 5.

## 3. Current state by page

| Page | State |
| --- | --- |
| Kiosk `/` (`templates/index.html`) | Redesigned. Light/dark, blue accent. Left: guide panel (name + status + voice switch, ID/EN/中文, character anchored bottom, mic dock). Middle: destination summary (only when a route exists) → map + directions side by side → search bar at the bottom (opens upward). Right: chat + slim room-status line. Static footer. On-screen keyboard for touch kiosks (`?kiosk=1` to force). Phones: search on top, chat as bottom sheet via floating guide-face button. Accepts `/?room=<id>` and `/?q=<question>`. |
| Web portal `/landing` | **Original page** plus layers: clouds/sky, darker hero, feature illustrations, floaters, lobbing arrow, real numbers, "Ask the AI" + Feedback + theme toggle in nav, floating "Rate us" tab. Campus photos captioned **KMG Campus**, **Alsut Campus** (tappable, opens the kiosk guide, live dot), ASO School of Engineering. |
| About `/about` | **Original page** plus: header actions, vertical story + 3D floor stack with red route, floaters behind stats, real "question phrasings" count. |
| Feedback `/feedback`, 404 | New design on the shared system (`site.css`), static footer (`_ticker.html` is now a static footer despite its name). |
| Admin (secret path) | Restyled on the shared tokens: light header, blue accent, theme-aware charts, visitor tables. |

## 4. Architecture notes

- **Shared system:** `static/css/sphere.css` (tokens light/dark, header `.deck`, buttons, chips, segmented switch, theme toggle, feedback tab + dialog, mesh background) and `static/js/sphere.js` (theme, `Flap`, clock, kinetic text, reveals, ripples, spotlight, feedback dialog, `keyedImage`, `/api/facts` counters). `static/js/theme-init.js` runs in `<head>` to avoid a theme flash.
- **Kiosk:** `kiosk.css` (base) + `kiosk-layout.css` (current layout, loaded after; it overrides older rules in `kiosk.css`). Map: `map.css`, `floor-map.js` (route draws itself, `locate()`).
- **Portal/About layers:** `landing-fx.css` + `landing-deco.css` + `landing-fx.js`, plus Jinja macros in `templates/_art.html`. Their original inline `<style>` blocks load **after** these files, so overrides sometimes need `!important` or higher specificity.
- **Server additions:** `/api/weather` (`server/weather.py`, Open-Meteo, free, cached 15 min, `WEATHER_LAT/LON`), `/api/facts` (rooms, floors, answer phrasings, languages), `asset_v` cache-busting on CSS/JS links (newest file mtime), feedback accepts a rating without a comment, admin lives under `ADMIN_PATH` (`/admin` returns 404).
- **No paid services anywhere** (owner asked to keep it that way): local chatbot, local Whisper, edge-tts (free) with offline fallback, Google Fonts, Open-Meteo.

## 5. Performance rules (learned the hard way)

1. No `backdrop-filter` on anything that sits over an animated background.
2. No `filter: blur()` on large animated layers; use `radial-gradient(... transparent)` instead.
3. No full-screen `mix-blend-mode` layers (the old grain was removed).
4. No `filter: drop-shadow()` on SVG parts that move every frame.
5. Pause what is off screen: `.fx-paused` + `svg.pauseAnimations()` (see `pauseOffscreen` in `landing-fx.js`). Canvas loops take an `isActive()` gate (`constellation.js`).
6. Animate `transform`/`opacity` only; never set CSS variables on `<html>` per frame.
7. `body` must use `overflow-x: clip`, not `hidden`, or `position: sticky` breaks (this broke the 3D stack once).
8. Gate hover lifts behind `@media (hover: hover) and (pointer: fine)` (touch kiosk).

## 6. Open items / next steps

- [ ] **Commit the work** (nothing is committed yet). Tool folders (`.playwright-mcp/`, `.impeccable/`, `.agents/`, `.claude/`) were deleted on 2026-10-11 and are git-ignored.
- [ ] Verify the tablet layout (900–1179 px) of the kiosk; the guide becomes a compact strip there and wasn't re-checked after the last layout change.
- [ ] Kiosk guide panel: some empty space between the language switch and the character at tall heights; consider a small "Try saying…" hint or larger character there.
- [ ] Dead CSS cleanup: older kiosk rules in `kiosk.css` superseded by `kiosk-layout.css`; `.dest-flap`, `.guide-halo`, `.chat-foot`, `.qr-card` rules are unused. `landing-fx.css` and `landing-deco.css` could be merged.
- [ ] The database has one closure (Library, Lantai 3, "closed", created 2026-10-06 by `infosphere_admin`). Owner may consider it a test entry; ask before deleting (Admin → Area status).
- [ ] Impeccable's formal finish review and `DESIGN.md` were not done (direction kept changing).
- [ ] Hosting (owner's plan): Railway or Fly.io with the Dockerfile and a volume at `/data`; set `ADMIN_USER`, `ADMIN_PASSWORD_HASH`, `SECRET_KEY`, `VISITOR_SALT`, `ADMIN_PATH`, `INFOSPHERE_ENV=production`, `TRUST_PROXY=1`, `INFOSPHERE_INSTANCE=/data`. Copy `instance/infosphere.db` to the volume first. Not Vercel.
- [ ] No team section on About: there are no real names/photos in the repo. Ask the owner for them; never invent people.

## 7. How to run and check

```bash
.venv/Scripts/python.exe app.py          # http://127.0.0.1:5000 (first start trains the chatbot)
python -m pytest -q                      # 60 tests, all passing at handoff
```

- Admin login: `http://127.0.0.1:5000/<ADMIN_PATH>/login` (value in `.env`). The password was given to the owner in chat; it is not stored anywhere in plain text.
- Playwright quirk seen this session: the test browser got stuck at 75% zoom and returned blank viewport screenshots of scrolled pages. Full-page capture + crop, or measuring state with `evaluate`, worked.
