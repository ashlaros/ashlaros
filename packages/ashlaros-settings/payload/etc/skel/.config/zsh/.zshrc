# manjaro-sway built on oh-my-zsh + powerlevel10k, neither of which Arch
# packages. Arch's own grml config covers the same ground - completion,
# history, keybindings, a prompt - and the two plugins below are what
# oh-my-zsh was actually being used for here.
source /etc/zsh/zshrc

source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# grml's prompt is fine on a dark terminal but reads as noise beside the
# stone accent; starship matches the rest of the desktop
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

# user-defined overrides
[ -d ~/.config/zsh/config.d/ ] && source <(cat ~/.config/zsh/config.d/*)

# Fix for foot terminfo not installed on most servers
alias ssh="TERM=xterm-256color ssh"
source ~/.config/user-dirs.dirs
