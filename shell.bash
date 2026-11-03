# Interactive Bash integration. `command sudo` always bypasses this function.
sudo() {
    "$HOME/.local/bin/pac-sudo" "$@"
}
