// Generated from docs/site.css by scripts/generate_style_module.py.
// Edit site.css, not this file.
//
// The worker serves this on every hostname, because docs/ is bound as
// static assets on the apex alone and packages. and iso. need the same
// bytes from their own origin.
export const STYLESHEET = `/*
 * The one stylesheet. Every page the worker serves is built from this:
 * the static pages under docs/, the game, and the directory listings the
 * worker renders in JS.
 *
 * One file, linked by every page rather than copied into each. The worker
 * serves it on all three hostnames the way it already serves favicon.svg,
 * so the apex, packages. and iso. get the same bytes from their own origin
 * and there is no second copy to drift. worker/src/style.js is generated
 * from this file; check.yml fails if it is stale.
 *
 * The design is manjaro-sway's, carried over from
 * sway-repo/_layouts/default.html: a #141a1b topbar, a #282828 page, #eee
 * foreground, headings deliberately small. Only the accent changed -
 * #16a085 was Manjaro's green; ours is stone.
 */

:root {
  /* branding/palette.conf, spelled in full six-digit hex. Three-digit is
     valid CSS but the same values feed starship, which silently drops a
     style containing #eee - one spelling everywhere is cheaper than
     remembering which consumer is fussy. */
  --base: #141a1b;
  --surface: #282828;
  --foreground: #eeeeee;
  --accent: #8a8f98;
  --highlight: #c9ccd1;
  --edge: #3a4043;
  --dim: #6b7280;
}

* {
  color: var(--foreground);
  text-decoration: none;
}

body {
  /* The generated wallpaper, which the prose pages had and the game pages
     did not - one of the inconsistencies this file exists to end. It is an
     SVG of the mark, so it costs almost nothing on either. */
  background-color: var(--surface);
  background-image: url('/background.svg');
  background-repeat: no-repeat;
  background-attachment: fixed;
  background-size: cover;
  background-position: center right;
  margin: 0;
  font-family: Roboto, Helvetica, Arial, sans-serif;
  /* a flex column so footer's margin-top: auto reaches the bottom of a
     short page */
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* The topbar. Every page has one and they are all the same height, so
   moving between them does not shift the content down. */
h1 {
  background: var(--base);
  color: var(--accent);
  font-size: 0.8rem;
  font-weight: 500;
  line-height: 30px;
  padding: 0 20px;
  margin: 0;
}

/* The project name in the topbar links home. The global rule paints every
   element with the foreground colour, which would make the name brighter
   than the page it names - so it inherits the heading's colour and only
   brightens on hover, like every other link here. */
h1 a {
  color: inherit;
}

h1 a:hover {
  color: var(--highlight);
}

h2 {
  color: var(--accent);
  font-size: 0.8rem;
  font-weight: 500;
  margin: 1.6rem 0 0.3rem;
}

/* A subdivision of the h2 above it - dimmer and closer to what it labels,
   so it reads as a grouping rather than a second list. */
h3 {
  color: var(--dim);
  font-size: 0.75rem;
  font-weight: 500;
  margin: 0.7rem 0 0.2rem;
}

main {
  margin: 20px;
  max-width: 60rem;
}

/* Prose wants a shorter measure than a table of downloads does. */
main.prose {
  max-width: 46rem;
}

p {
  line-height: 1.6;
  max-width: 40rem;
}

ul {
  line-height: 1.8;
  padding-left: 1.2rem;
  max-width: 40rem;
}

pre {
  background: var(--base);
  padding: 0.8rem 1rem;
  overflow-x: auto;
}

pre,
code {
  font-family: monospace;
  color: var(--highlight);
}

a.link {
  font-family: monospace;
  text-shadow: 2px 2px var(--surface);
}

a:hover,
a.link:hover,
.row:hover {
  color: var(--highlight);
}

.muted {
  color: var(--accent);
}

table {
  border-collapse: collapse;
  font-family: monospace;
}

td {
  padding: 2px 20px 2px 0;
  white-space: nowrap;
}

td:not(:first-child) {
  color: var(--accent);
}

.row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.15rem 0;
  font-family: monospace;
}

/* The footer carries the policy links, which an OAuth review looks for on
   the homepage. margin-top: auto against the flex body puts it at the
   bottom of a short page and after the content on a long one. */
footer {
  margin-top: auto;
  background: var(--base);
  padding: 0.7rem 20px;
  font-size: 0.8rem;
}

/* Images carry width and height attributes too: no external stylesheet
   means a late-loading image would otherwise reflow everything under it. */
.frame {
  width: 100%;
  height: auto;
  display: block;
  border: 1px solid var(--edge);
  background: var(--base);
}

.frame[hidden] {
  display: none;
}

.gallery {
  margin: 0 0 1.6rem;
  position: relative;
}

.gallery:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 4px;
}

.nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  background: var(--base);
  color: var(--highlight);
  border: 1px solid var(--edge);
  font-size: 1.4rem;
  line-height: 1;
  padding: 0.3rem 0.6rem;
  cursor: pointer;
}

.nav:hover {
  border-color: var(--accent);
}

/* Disabled at the ends rather than wrapping: four frames is a short set to
   be thrown back to the start of. */
.nav[disabled] {
  opacity: 0.3;
  pointer-events: none;
}

.prev {
  left: 0.4rem;
}

.next {
  right: 0.4rem;
}

.shot-caption {
  color: var(--accent);
  font-size: 0.85rem;
  padding-top: 0.5rem;
}

.dots {
  display: flex;
  gap: 0.4rem;
  padding-top: 0.5rem;
}

.dot {
  width: 0.6rem;
  height: 0.6rem;
  padding: 0;
  border: 0;
  background: var(--edge);
  cursor: pointer;
}

.dot[aria-selected='true'] {
  background: var(--accent);
}

/* Without JavaScript every frame is shown in order, which is a longer page
   rather than a broken one. */
.no-js .frame[hidden] {
  display: block;
  margin-top: 0.6rem;
}

.no-js .nav,
.no-js .dots {
  display: none;
}

/* max-width rather than a fixed width: a fixed 960px on a 390px phone put
   the right edge off the screen. */
.tour {
  max-width: 100%;
  border: 1px solid var(--edge);
}

canvas {
  background: #0d1112;
  border: 1px solid var(--edge);
  touch-action: none;
}

/*
 * The arcade. Both games render the same furniture - a board, a score, a
 * leaderboard beside it - so these live here rather than twice.
 */

/* The leaderboard beside the board. flex: 1 with a basis, not min-width
   alone: min-width sets a floor and nothing stops it growing, so at 960px
   it took 640px next to a 302px canvas and the two wrapped onto separate
   rows - measured, after the shared stylesheet dropped the width the game
   pages used to carry. */
aside {
  font-family: monospace;
  flex: 1 1 16rem;
  min-width: 16rem;
  max-width: 24rem;
}

.score {
  color: var(--foreground);
  font-size: 1.6rem;
}

button,
input {
  background: var(--base);
  border: 1px solid var(--edge);
  color: var(--foreground);
  font-family: monospace;
  padding: 0.4rem 0.7rem;
}

button:hover {
  color: var(--highlight);
}

/* Three windows, because scores from different seeds are not comparable:
   a single table of best runs ranks the kindest seed rather than the best
   play. */
.tabs {
  display: flex;
  gap: 0.4rem;
  margin: 0 0 0.6rem;
}

.tabs button {
  font-size: 0.7rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 0.25rem 0.5rem;
}

.tabs button[aria-current='true'],
.initials button[aria-current='true'] {
  color: var(--highlight);
  border-color: var(--highlight);
}

/* Three characters the player cycles, not a text field: entering initials
   is the arcade ritual and it is the moment the score becomes theirs. */
.initials button {
  font-size: 2rem;
  padding: 0.2rem 0.6rem;
  margin-right: 0.3rem;
  border-color: var(--edge);
}

/* The game wants its board and leaderboard side by side and centred; the
   prose pages want a left-aligned column. */
main.game {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
  /* max-width is load-bearing, not decoration: without it main fills the
     row, the auto margins have nothing to centre against and compute to 0,
     and the board and leaderboard wrap onto separate lines. Measured at
     900px - canvas at y=50, aside at y=744 - before this was put back. */
  max-width: 60rem;
  margin: 20px auto;
}
`;
