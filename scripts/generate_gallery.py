#!/usr/bin/env python3
"""Generate the landing page's slideshow from shots.yaml.

The page showed one screenshot out of the four the capture job publishes,
plus a tour video nobody could reach from it (#69). This emits the
<figure> that shows all of them.

Generated rather than hand-written for the reason generate-script.py
exists: shots.yaml is already the list of what gets captured and
uploaded, and a second copy in index.html is a second thing to keep in
step. Adding a shot is a YAML entry and a re-run.

The page ships no stylesheet and no framework, so the markup carries its
own styles and the behaviour is one inline script. It degrades: with
JavaScript off, every frame is visible in document order with its caption,
which is a longer page rather than a broken one.
"""

import argparse
import html
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "screenshots" / "shots.yaml"
PAGE = ROOT / "docs" / "index.html"
BASE = "https://ashlaros.download/iso/latest"

# Where the generated block begins and ends. Markers rather than a line
# range: the page is edited by hand around this, and a range goes stale
# the first time someone adds a paragraph above it.
START = "      <!-- BEGIN generated gallery: scripts/generate_gallery.py -->"
END = "      <!-- END generated gallery -->"


def frames() -> list[dict]:
    """Every slide, in the order shots.yaml lists them, video last.

    The description in shots.yaml is written to explain the capture to
    whoever maintains it, and it reads correctly as alt text - "three
    terminals tiled, which is what the window manager is for" tells a
    screen reader exactly what a sighted visitor sees.
    """
    shots = yaml.safe_load(SHOTS.read_text())
    out = [
        {
            "kind": "image",
            "src": f"{BASE}/screenshots/{shot['name']}.png",
            "alt": f"AshlarOS: {shot['description']}",
            "caption": shot["description"],
        }
        for shot in shots
    ]
    # The tour is one file the record job always writes under this name,
    # so it is not in shots.yaml to be read from. It goes last because it
    # is the longest thing to load and the least likely to be wanted
    # first.
    out.append(
        {
            "kind": "video",
            "src": f"{BASE}/video/tour.webm",
            "alt": "A short silent tour of the desktop",
            "caption": "a short silent tour: tiling, the launcher, the theme switching",
            # the first screenshot, so the video has something to show
            # before it is played rather than a black rectangle
            "poster": f"{BASE}/screenshots/{shots[0]['name']}.png",
        }
    )
    return out


def render(items: list[dict]) -> str:
    parts = [
        START,
        '      <figure class="gallery" tabindex="0" role="region"',
        '        aria-roledescription="carousel"',
        '        aria-label="Screenshots of the AshlarOS desktop">',
        '        <div class="frames">',
    ]

    for index, item in enumerate(items):
        # width and height on every frame, not just the first: the page
        # has no stylesheet to reserve the box, so a frame that arrives
        # without them reflows everything below it on every slide change
        hidden = "" if index == 0 else " hidden"
        alt = html.escape(item["alt"], quote=True)
        if item["kind"] == "image":
            parts.append(
                f'          <img class="frame"{hidden} src="{item["src"]}"'
                f' alt="{alt}" width="1920" height="1080"'
                # only the first frame is fetched on load; the rest when
                # they are first shown
                f' loading="{"eager" if index == 0 else "lazy"}" />'
            )
        else:
            parts.append(
                f'          <video class="frame"{hidden} src="{item["src"]}"'
                f' poster="{item["poster"]}" width="1920" height="1080"'
                f' controls preload="none" aria-label="{alt}"></video>'
            )

    parts += [
        "        </div>",
        '        <button class="nav prev" type="button"'
        ' aria-label="Previous screenshot">&#x2039;</button>',
        '        <button class="nav next" type="button"'
        ' aria-label="Next screenshot">&#x203a;</button>',
        f'        <figcaption class="shot-caption">{html.escape(items[0]["caption"])}</figcaption>',
        '        <div class="dots" role="tablist" aria-label="Choose a screenshot">',
    ]
    for index, item in enumerate(items):
        selected = "true" if index == 0 else "false"
        label = html.escape(item["caption"], quote=True)
        parts.append(
            f'          <button class="dot" type="button" role="tab"'
            f' aria-selected="{selected}" aria-label="{label}"></button>'
        )
    parts += [
        "        </div>",
        "      </figure>",
        END,
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the page is not what this would generate",
    )
    args = parser.parse_args()

    page = PAGE.read_text()
    if START not in page or END not in page:
        print(f"{PAGE} has no generated-gallery markers", file=sys.stderr)
        return 1

    before = page[: page.index(START)]
    after = page[page.index(END) + len(END) :]
    updated = before + render(frames()) + after

    if args.check:
        if updated != page:
            print(
                "docs/index.html is out of date: run scripts/generate_gallery.py",
                file=sys.stderr,
            )
            return 1
        print("the gallery matches shots.yaml")
        return 0

    if updated == page:
        print("already up to date")
        return 0
    PAGE.write_text(updated)
    print(f"wrote {len(frames())} frames into {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
