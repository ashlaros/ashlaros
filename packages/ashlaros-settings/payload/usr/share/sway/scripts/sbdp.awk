# Sway Binding Documentation Parser.
#
# Flattens a sway config, finds `## Category // Action // Keybinding ##`
# comments, resolves $variables, and emits one record per binding: the
# category, the action, the rendered keybinding, which of Super, Shift,
# Ctrl and Alt it needs, and the mode it belongs to - the two things the
# help overlay filters on while keys are held (#89).
#
# Records are \x1f-delimited, not tab-delimited. An action containing a tab
# silently split into the wrong fields under TSV, and that is the first
# thing that broke when this was written - `## Tabs // Action\twith\ttabs //
# Super + e ##` parsed as action="Action", keybinding="with".
#
# Two shell-outs, for the two jobs awk genuinely cannot do: `ls -d` expands
# the glob in an `include` line, and `printf '%s'` expands $HOME and friends
# the way os.path.expandvars did. Both close() the exact command string they
# opened - rebuilding it from a variable that getline had overwritten leaves
# the pipe open, and mawk then leaks "Unterminated quoted string" to stderr
# where gawk hides it.

function expand(path,   cmd, out) {
	cmd = "printf '%s' \"" path "\""
	cmd | getline out
	close(cmd)
	return out == "" ? path : out
}

function readfile(path,   cmd, file, line, next_path, more) {
	path = expand(path)
	# ls -d rather than a glob loop: awk has no globbing.
	#
	# This changes the help overlay's order, deliberately. glob.glob
	# returned readdir order, help.sh sorts by category, and jq's sort_by
	# is stable - so file order decided ties within a category. Same 45
	# entries either way, measured; different order. Sorted is the
	# defensible one, because readdir order is filesystem-dependent and two
	# machines with the same config could render the list differently.
	cmd = "ls -d " path " 2>/dev/null"
	while ((cmd | getline file) > 0) {
		while ((getline line < file) > 0) {
			# A trailing backslash continues the line, as sway reads it:
			# every mode's name is a `set` spread over several lines, and
			# kept one line at a time the variable held only the first.
			while (line ~ /\\$/ && (getline more < file) > 0)
				line = substr(line, 1, length(line) - 1) more
			# Variables are collected as the files are read, in order, the
			# way sway reads them - so `include $theme/theme.conf` resolves
			# $theme, which the shell would have read as empty and dropped
			# the whole theme, and with it every colour the mode names are
			# written in.
			if (line ~ /^set[ \t]+\$/) set_var(line)
			if (line ~ /^include[ \t]+/) {
				next_path = line
				sub(/^include[ \t]+/, "", next_path)
				readfile(substitute(next_path))
			} else {
				nlines++
				lines[nlines] = line
			}
		}
		close(file)
	}
	close(cmd)
}

# `set $variable value`, which the keybindings are written in terms of. The
# value is substituted when it is set, as sway does: `set $accent-color
# $color12` holds the colour, not the name of another variable.
function set_var(line,   name, value) {
	name = line
	sub(/^set[ \t]+/, "", name)
	value = name
	sub(/^[^ \t]+[ \t]+/, "", value)
	sub(/[ \t].*$/, "", name)
	if (name != "" && value != name)
		vars[name] = substitute(value)
}

# Every $name inside a string, as sway substitutes them: longest name
# first, so $color10 is never read as $color1 followed by a 0.
function substitute(text,   changed, name, best, pos, tries) {
	for (tries = 0; tries < 100 && index(text, "$"); tries++) {
		best = ""
		for (name in vars)
			if (index(text, name) && length(name) > length(best)) best = name
		if (best == "") break
		pos = index(text, best)
		text = substr(text, 1, pos - 1) vars[best] substr(text, pos + length(best))
	}
	return text
}

function translate(word) {
	gsub(/^[ \t]+|[ \t]+$/, "", word)
	if (word in vars) word = vars[word]
	gsub(/^[ \t]+|[ \t]+$/, "", word)
	if (word in keys) return keys[word]
	return word
}

# A binding written in the comment's own third field is already prose -
# "$mod + ↑ ↓ ← →", "+ -" - and is only resolved word by word, so a "+" or
# "-" that IS the key survives. Only a sway key spec lifted from the line
# below, "$mod+Shift+q", is split on "+" into a chord.
function render_binding(binding, written,   n, parts, i, out) {
	if (written) {
		n = split(binding, parts, " ")
		out = ""
		for (i = 1; i <= n; i++)
			out = out (i > 1 ? " " : "") (parts[i] == "+" ? "+" : translate(parts[i]))
		return out
	}
	n = split(binding, parts, "+")
	out = ""
	for (i = 1; i <= n; i++)
		out = out (i > 1 ? " + " : "") translate(parts[i])
	return out
}

# The modifiers a binding needs, as a fixed four-letter mask - s for Super,
# h for sHift, c for Ctrl, a for Alt, "-" where one is not needed - so the
# overlay compares it with the held set as one string rather than parsing.
# Read off the rendered names, which translate() has already mapped Mod4
# and Mod1 onto, and only ever off the modifier positions: every part but
# the last, since "+" and "-" are keys of their own as well.
function modifiers(rendered,   n, parts, i, part, mask) {
	mask["Super"] = "-"; mask["Shift"] = "-"; mask["Ctrl"] = "-"; mask["Alt"] = "-"
	n = split(rendered, parts, " \\+ ")
	for (i = 1; i < n; i++) {
		part = parts[i]
		if (part == "Control") part = "Ctrl"
		if (part in mask) mask[part] = substr(part == "Shift" ? "h" : tolower(part), 1, 1)
	}
	return mask["Super"] mask["Shift"] mask["Ctrl"] mask["Alt"]
}

# The mode a line sits in, tracked by brace depth across `mode ... {`
# blocks. Recorded as the mode's own name after $variables, which is the
# string sway reports in its mode event - so the overlay compares the two
# directly. Those names are pango markup here, with the theme's colours
# resolved into them; comparing them whole is what keeps two modes that
# happen to share a word apart.
function mode_of(line,   name) {
	if (line ~ /^[ \t]*mode[ \t]/ && line ~ /\{[ \t]*$/) {
		name = line
		sub(/^[ \t]*mode[ \t]+(--pango_markup[ \t]+)?/, "", name)
		sub(/[ \t]*\{[ \t]*$/, "", name)
		gsub(/^"|"$/, "", name)
		current_mode = substitute(name)
		gsub(/^"|"$/, "", current_mode)
		depth = 1
		return
	}
	if (current_mode != "default") {
		depth += gsub(/\{/, "{", line) - gsub(/\}/, "}", line)
		if (depth <= 0) current_mode = "default"
	}
}

BEGIN {
	US = sprintf("%c", 31)
	current_mode = "default"

	keys["Mod1"] = "Alt"
	keys["Mod2"] = MOD2
	keys["Mod3"] = MOD3
	# the super key, not a distro badge
	keys["Mod4"] = "Super"
	keys["Mod5"] = "Scroll"
	keys["question"] = "?"
	keys["space"] = SPACE
	keys["minus"] = "-"
	keys["plus"] = "+"
	keys["Return"] = RETURN
	keys["XF86AudioRaiseVolume"] = VOL_UP
	keys["XF86AudioLowerVolume"] = VOL_DOWN
	keys["XF86AudioMute"] = VOL_MUTE
	keys["XF86AudioMicMute"] = MIC_MUTE
	keys["XF86MonBrightnessUp"] = BRIGHT_UP
	keys["XF86MonBrightnessDown"] = BRIGHT_DOWN
	keys["XF86PowerOff"] = POWER
	keys["XF86TouchpadToggle"] = "Toggle Touchpad"

	readfile(ROOT)

	for (i = 1; i <= nlines; i++) {
		line = lines[i]
		mode_of(line)
		# Indented as well: a comment inside a `mode { }` block is written
		# with the block's indentation, and anchoring at column 0 dropped
		# every one of them - the resize mode's gap keys never reached the
		# sheet (#89).
		if (line !~ /^[ \t]*## .+ \/\/ /) continue

		body = line
		sub(/^[ \t]*## /, "", body)
		sub(/[ \t]*##.*$/, "", body)

		sep = index(body, " // ")
		if (sep == 0) continue
		category = substr(body, 1, sep - 1)
		rest = substr(body, sep + 4)

		sep = index(rest, " // ")
		written = sep > 0
		if (written) {
			action = substr(rest, 1, sep - 1)
			binding = substr(rest, sep + 4)
		} else {
			action = rest
			# No third field: the binding is the second word of the line
			# below, which is what `$bindsym $mod+d exec ...` puts there.
			binding = ""
			if (i < nlines) {
				split(lines[i + 1], f, " ")
				# `$bindsym --locked Key cmd`: the key is the first word
				# after the flags, not the second word of the line
				for (k = 2; k in f && f[k] ~ /^--/; k++) ;
				binding = f[k]
			}
		}
		gsub(/[ \t]+$/, "", action)
		gsub(/^[ \t]+|[ \t]+$/, "", binding)

		rendered = render_binding(binding, written)
		printf "%s%s%s%s%s%s%s%s%s\n", category, US, action, US, rendered, US, \
			modifiers(rendered), US, current_mode
	}
}
