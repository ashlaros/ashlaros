#!/usr/bin/env python3
"""Generate the plymouth script from logo.txt.

The mark is three courses of dressed stone with offset joints. Plymouth's
script language has no file I/O, so the rows have to be literals inside
it - which is exactly how a theme drifts from the favicon it was traced
from. Generating them here means logo.txt stays the one source: change a
row there, run this, and the splash follows.

ashlaros-branding runs this at build time, so a checkout can never ship a
script that disagrees with the logo beside it.
"""

import pathlib
import sys

# branding/palette.conf, as plymouth wants them: floats, not hex
STONE = (0xEE / 255, 0xEE / 255, 0xEE / 255)
ACCENT = (0x8A / 255, 0x8F / 255, 0x98 / 255)
BASE = (0x14 / 255, 0x1A / 255, 0x1B / 255)


def rows_from(logo: pathlib.Path) -> tuple[list[str], str]:
    lines = logo.read_text().splitlines()
    courses = [line for line in lines[:6]]
    # the name is whatever follows the six course rows, blank lines
    # dropped - read back rather than assuming row 8 survives a reflow,
    # the same rule ashlaros-logo-animate follows
    name = next((line for line in lines[6:] if line.strip()), "")
    return courses, name


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <logo.txt> <out.script>", file=sys.stderr)
        return 2

    courses, name = rows_from(pathlib.Path(sys.argv[1]))
    if len(courses) < 6:
        print("logo.txt has fewer than six course rows", file=sys.stderr)
        return 1

    rows = ",\n  ".join(f'"{row}"' for row in courses)

    script = f'''# AshlarOS boot splash. GENERATED from branding/logo.txt by
# branding/plymouth/generate-script.py - edit the logo, not this file.
#
# Three courses of dressed stone appear in sequence, then the name resolves
# underneath: a wall being built, held for a beat, done. Not a spinner, and
# not a progress bar - the boot is as long as it is, and pretending to
# measure it would be a lie drawn at 30fps.
#
# The animation must never hold the boot. Plymouth tears the splash down
# when the system is ready, mid-frame if need be, which is the correct
# behaviour: a splash that outlasts the boot is a delay.

Window.SetBackgroundTopColor({BASE[0]:.4f}, {BASE[1]:.4f}, {BASE[2]:.4f});
Window.SetBackgroundBottomColor({BASE[0]:.4f}, {BASE[1]:.4f}, {BASE[2]:.4f});

course_rows = [
  {rows}
];

name_text = "{name}";

# One course is two rows, so three courses is six - the favicon's own
# structure, not a number picked for the animation.
rows_per_course = 2;
course_count = 3;

# Tuned so all three courses and the name land inside a second: this runs
# ahead of a boot, not in place of one.
frames_per_course = 8;
frames_per_letter = 2;

fun row_sprite (text, index, dim) {{
  colour = dim ? {ACCENT[0]:.4f} : {STONE[0]:.4f};
  image = Image.Text(text, colour, dim ? {ACCENT[1]:.4f} : {STONE[1]:.4f},
                     dim ? {ACCENT[2]:.4f} : {STONE[2]:.4f});
  sprite = Sprite(image);
  sprite.SetX(Window.GetWidth() / 2 - image.GetWidth() / 2);
  sprite.SetY(Window.GetHeight() / 2 - (image.GetHeight() * 5) + index * image.GetHeight());
  sprite.SetZ(1);
  return sprite;
}}

global.shown = 0;
global.letters = 0;
global.tick = 0;
global.sprites = [];
global.name_sprite = NULL;

fun show_course (course) {{
  for (row = 0; row < rows_per_course; row++) {{
    index = course * rows_per_course + row;
    global.sprites[index] = row_sprite(course_rows[index], index, 0);
  }}
}}

fun show_name (letters) {{
  if (name_text == "") return;
  # Step over visible characters: the name is letter-spaced, so counting
  # columns would spend half the reveal on spaces.
  text = StringCopy(name_text, 0, letters);
  image = Image.Text(text, {STONE[0]:.4f}, {STONE[1]:.4f}, {STONE[2]:.4f});
  if (global.name_sprite) global.name_sprite.SetImage(image);
  else global.name_sprite = Sprite(image);
  global.name_sprite.SetX(Window.GetWidth() / 2 - image.GetWidth() / 2);
  global.name_sprite.SetY(Window.GetHeight() / 2 + image.GetHeight());
  global.name_sprite.SetZ(1);
}}

fun refresh_callback () {{
  global.tick++;

  if (global.shown < course_count) {{
    if (global.tick >= frames_per_course) {{
      show_course(global.shown);
      global.shown++;
      global.tick = 0;
    }}
    return;
  }}

  if (global.letters < StringLength(name_text)) {{
    if (global.tick >= frames_per_letter) {{
      global.letters++;
      show_name(global.letters);
      global.tick = 0;
    }}
  }}
}}

Plymouth.SetRefreshFunction(refresh_callback);

# The passphrase prompt, drawn inside the splash rather than tearing it
# down. On an encrypted install without TPM enrolment this is the whole
# boot experience, so it is the part that has to be right: a splash that
# hides the prompt is worse than no splash, because the machine looks hung.
global.prompt_sprite = NULL;
global.bullet_sprite = NULL;

fun display_password_callback (prompt, bullets) {{
  image = Image.Text(prompt, {STONE[0]:.4f}, {STONE[1]:.4f}, {STONE[2]:.4f});
  if (global.prompt_sprite) global.prompt_sprite.SetImage(image);
  else global.prompt_sprite = Sprite(image);
  global.prompt_sprite.SetX(Window.GetWidth() / 2 - image.GetWidth() / 2);
  global.prompt_sprite.SetY(Window.GetHeight() / 2 + image.GetHeight() * 4);
  global.prompt_sprite.SetZ(2);

  # One block per typed character: the passphrase is never echoed, but
  # silence on keypress is indistinguishable from a dead keyboard.
  dots = "";
  for (index = 0; index < bullets; index++) dots += "*";
  dot_image = Image.Text(dots, {ACCENT[0]:.4f}, {ACCENT[1]:.4f}, {ACCENT[2]:.4f});
  if (global.bullet_sprite) global.bullet_sprite.SetImage(dot_image);
  else global.bullet_sprite = Sprite(dot_image);
  global.bullet_sprite.SetX(Window.GetWidth() / 2 - dot_image.GetWidth() / 2);
  global.bullet_sprite.SetY(Window.GetHeight() / 2 + dot_image.GetHeight() * 6);
  global.bullet_sprite.SetZ(2);
}}

fun display_normal_callback () {{
  if (global.prompt_sprite) global.prompt_sprite.SetOpacity(0);
  if (global.bullet_sprite) global.bullet_sprite.SetOpacity(0);
}}

Plymouth.SetDisplayPasswordFunction(display_password_callback);
Plymouth.SetDisplayNormalFunction(display_normal_callback);

# A failed unlock or an fsck question has to reach the screen too, or the
# machine sits at a splash waiting for an answer nobody can see.
fun display_message_callback (text) {{
  image = Image.Text(text, {ACCENT[0]:.4f}, {ACCENT[1]:.4f}, {ACCENT[2]:.4f});
  global.message_sprite = Sprite(image);
  global.message_sprite.SetX(Window.GetWidth() / 2 - image.GetWidth() / 2);
  global.message_sprite.SetY(Window.GetHeight() / 2 + image.GetHeight() * 8);
  global.message_sprite.SetZ(2);
}}

Plymouth.SetMessageFunction(display_message_callback);
'''

    pathlib.Path(sys.argv[2]).write_text(script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
