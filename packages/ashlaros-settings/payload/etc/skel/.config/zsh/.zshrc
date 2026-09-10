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

# user-defined overrides
[ -d ~/.config/zsh/config.d/ ] && source <(cat ~/.config/zsh/config.d/*)

# Fix for foot terminfo not installed on most servers
alias ssh="TERM=xterm-256color ssh"
source ~/.config/user-dirs.dirs
