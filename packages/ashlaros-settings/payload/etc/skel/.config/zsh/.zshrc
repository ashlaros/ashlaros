# manjaro-sway built on oh-my-zsh + powerlevel10k, neither of which Arch
# packages. Arch's own grml config covers the same ground - completion,
# history, keybindings, a prompt - and the two plugins below are what
# oh-my-zsh was actually being used for here.
source /etc/zsh/zshrc

source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# grml's prompt is fine on a dark terminal but reads as noise beside the
# stone accent. grml rebuilds PROMPT on every command, which silently
# clobbers what starship init sets, so it must be disabled explicitly
prompt off
command -v starship >/dev/null && eval "$(starship init zsh)"

ZSH_HIGHLIGHT_STYLES[comment]='fg=blue'

# fzf's key bindings are the whole point of installing it: ^R over history
# and ^T over files. Sourced rather than assumed present, like starship
# above - this file is skel and survives the package being removed.
[ -f /usr/share/fzf/key-bindings.zsh ] && source /usr/share/fzf/key-bindings.zsh
[ -f /usr/share/fzf/completion.zsh ] && source /usr/share/fzf/completion.zsh

# zoxide shadows nothing: `cd` keeps working and `z` is the frecency jump
command -v zoxide >/dev/null && eval "$(zoxide init zsh)"

# Runtime versions - node, python, go - per project. Prompt activation
# rather than --shims: it is what mise's own docs lead with and shims do
# not support the full feature set. The guard is load-bearing, not
# decoration: mise does not exist on ARM at all, and an unguarded eval
# would print an error on every shell start there.
command -v mise >/dev/null && eval "$(mise activate zsh)"

# A multiplexer in a foot window marks the window with its own app_id, so
# sworkstyle can give that workspace the multiplexer icon: sworkstyle
# matches app_id, class and title only, and none of tmux, zellij or herdr
# puts its name in the title by default. OSC 176 is foot's; other
# terminals ignore it. preexec's $2 has aliases expanded, so `t` aliased
# to tmux counts; the first word after sudo/env/exec is what runs. Reset
# before each prompt, so detaching or quitting gives the window back.
if [[ $TERM == foot* ]]; then
  _ashlaros_mux_appid() {
    local -a words=(${(z)2})
    while [[ ${words[1]-} == (sudo|env|exec|command|nohup|*=*) ]]; do
      shift words
    done
    case ${words[1]:t} in
      tmux | zellij | herdr) printf '\e]176;terminal-multiplexer\e\\' ;;
    esac
  }
  _ashlaros_mux_reset() { printf '\e]176;\e\\'; }
  autoload -Uz add-zsh-hook
  add-zsh-hook preexec _ashlaros_mux_appid
  add-zsh-hook precmd _ashlaros_mux_reset
fi

# user-defined overrides
[ -d ~/.config/zsh/config.d/ ] && source <(cat ~/.config/zsh/config.d/*)

# Fix for foot terminfo not installed on most servers
alias ssh="TERM=xterm-256color ssh"
source ~/.config/user-dirs.dirs
