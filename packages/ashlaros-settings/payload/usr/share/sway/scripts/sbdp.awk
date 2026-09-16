# Sway Binding Documentation Parser.
#
# Flattens a sway config, finds `## Category // Action // Keybinding ##`
# comments, resolves $variables, and emits one record per binding.
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

function readfile(path,   cmd, file, line, next_path) {
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
			if (line ~ /^include[ \t]+/) {
				next_path = line
				sub(/^include[ \t]+/, "", next_path)
				readfile(next_path)
			} else {
				nlines++
				lines[nlines] = line
			}
		}
		close(file)
	}
	close(cmd)
}

# `set $variable value`, which the keybindings are written in terms of.
function collect_vars(   i, line, name, value) {
	for (i = 1; i <= nlines; i++) {
		line = lines[i]
		if (line ~ /^set[ \t]+\$/) {
			name = line
			sub(/^set[ \t]+/, "", name)
			value = name
			sub(/^[^ \t]+[ \t]+/, "", value)
			sub(/[ \t].*$/, "", name)
			if (name != "" && value != name)
				vars[name] = value
		}
	}
}

function translate(word) {
	gsub(/^[ \t]+|[ \t]+$/, "", word)
	if (word in vars) word = vars[word]
	gsub(/^[ \t]+|[ \t]+$/, "", word)
	if (word in keys) return keys[word]
	return word
}

function render_binding(binding,   n, parts, i, out) {
	n = split(binding, parts, "+")
	out = ""
	for (i = 1; i <= n; i++)
		out = out (i > 1 ? " + " : "") translate(parts[i])
	return out
}

BEGIN {
	US = sprintf("%c", 31)

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
	collect_vars()

	for (i = 1; i <= nlines; i++) {
		line = lines[i]
		if (line !~ /^## .+ \/\/ /) continue

		body = line
		sub(/^## /, "", body)
		sub(/[ \t]*##.*$/, "", body)

		sep = index(body, " // ")
		if (sep == 0) continue
		category = substr(body, 1, sep - 1)
		rest = substr(body, sep + 4)

		sep = index(rest, " // ")
		if (sep > 0) {
			action = substr(rest, 1, sep - 1)
			binding = substr(rest, sep + 4)
		} else {
			action = rest
			# No third field: the binding is the second word of the line
			# below, which is what `$bindsym $mod+d exec ...` puts there.
			binding = ""
			if (i < nlines) {
				split(lines[i + 1], f, " ")
				binding = f[2]
			}
		}
		gsub(/[ \t]+$/, "", action)
		gsub(/^[ \t]+|[ \t]+$/, "", binding)

		printf "%s%s%s%s%s\n", category, US, action, US, render_binding(binding)
	}
}
