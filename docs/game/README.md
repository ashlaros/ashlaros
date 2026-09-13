# The game page

`logic.js` here is **generated** from `worker/src/game/logic.js and quarry.js` and is not
committed. `npm run game:sync` in `worker/` copies it, and `npm test` and
the deploy both run that first.

The reason it is a copy at all: `docs/` is uploaded to Cloudflare as static
assets, so a module here cannot import from `../../worker/src/`. The copy is
generated rather than maintained for exactly the reason the plymouth theme
script is generated from `logo.txt` — a hand-maintained second copy of a
simulation is the drift this whole design exists to prevent, and two
implementations that disagree reject every honest score.

If you edit the simulation, edit `worker/src/game/logic.js and quarry.js`. Nothing here.
