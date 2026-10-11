# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Kiosk walk-ups at a BINUS University campus building**: new students, visitors and parents standing at a touch-screen kiosk who need to find a room, office or facility (for example Admisi, Library, C0207) quickly. Short sessions, often hurried, sometimes not fluent in Bahasa Indonesia.
- **The same people on their phones**: they scan the "take the route on your phone" QR code, or open the web portal directly, and use it one-handed while walking.
- **Campus staff (admins)**: sign in to the admin area to read visits, chatbot quality and site feedback, teach missing answers, and mark areas as closed or under construction.

## Product Purpose

Infosphere is a campus wayfinding kiosk with an AI guide. A visitor types or speaks a question in Bahasa Indonesia, English or Mandarin; the guide answers, and the floor map draws the walking route from the kiosk to the destination with step-by-step directions. Success means a visitor leaves the kiosk knowing exactly where to walk, in their own language, within a minute.

## Positioning

A physical kiosk that knows where it stands: every route starts from the kiosk's real position on the real floor plan, closures set by staff appear on the map in real time, and the same route can be carried to a phone by QR code. The chatbot runs locally, with no paid AI service behind it.

## Operating Context

- Primary display: a large touch screen in a campus lobby (landscape, ~1280-1920 px wide), used standing, under indoor lighting, by strangers who have never seen it before. Physical keyboards are not present at the kiosk.
- Secondary: phones (375-430 px), via QR hand-off or the web portal (`/landing`).
- Pages: kiosk (`/`), web portal (`/landing`), About (`/about`), feedback (`/feedback`), admin (secret path), 404.
- Voice in and out: speech-to-text (browser or local Whisper), spoken answers (edge-tts with offline fallback), a quiet mode that mutes audio.

## Capabilities and Constraints

- Flask + Jinja templates, plain HTML/CSS/JavaScript, no build step. Vendored GSAP + ScrollTrigger and Chart.js are available under `static/vendor/`.
- Strict Content-Security-Policy: scripts only from `'self'` plus per-request nonces on public pages; admin pages allow no inline scripts. Styles may come from Google Fonts. `connect-src 'self'` (external data must be proxied by the server).
- Data sources: `/rooms.json` (floors, rooms, kiosk position), `/api/closures`, `/chat`, `/speak`, `/transcribe`, `/feedback/submit`, `/qr`.
- Weather: live temperature fetched by the server from Open-Meteo (free, no key), hidden when unavailable. (Confirmed 2026-10-10.)
- On-screen keyboard: shown only on large touch screens or with `?kiosk=1`, never on phones or mouse-driven desktops. (Confirmed 2026-10-10.)
- All existing functionality and all three languages (ID / EN / 中文) must keep working.

## Brand Commitments

- Name: **Infosphere** (wordmark "infosphere"); logo files in `static/brand/`.
- The AI guide is an illustrated character with five states (idle, speak, thinking, waving, default) in `static/img/character/`.
- Colour identity: delegated to the designer (2026-10-10); the previous look was BINUS-style blue with an orange focus ring.

## Evidence on Hand

- Real floor plans for floors 1-4 (`static/maps/`), real room list and kiosk position (`data/rooms.json`), real Q&A dataset (`data/qa/`).
- Campus photos `static/img/img1-3.jpg`.
- No testimonials, usage statistics or partner logos exist; do not fabricate them.

## Product Principles

1. The route is the answer: every interaction should end with the visitor knowing where to walk.
2. Strangers, standing, in a hurry: legible at arm's length, obvious on first sight, no hidden gestures.
3. Three languages are equal citizens; nothing may only work in Bahasa Indonesia.
4. Live truth over decoration: closures, the kiosk position and the clock are real.
5. Motion must explain or acknowledge, never slow the visitor down.

## Accessibility & Inclusion

WCAG 2.1 AA contrast in light and dark themes, visible focus, full keyboard operation, labelled icon buttons, `prefers-reduced-motion` honoured, touch targets of at least 44 px.
