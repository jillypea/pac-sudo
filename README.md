# Pac-Sudo

A small Python program for Kitty that masks the sudo password with stars, then
animates a yellow ASCII Pac-Man eating those stars after sudo accepts it.
Python 3.14 or newer is required; there are no third-party dependencies.

## Install

Requires Linux, Bash, Python 3.14 or newer, and sudo at `/usr/bin/sudo`.
The animation is tested in Kitty.

Clone the project and link the launcher into your user-local bin directory:

```bash
mkdir -p ~/Projects ~/.local/bin
git clone https://github.com/jillypea/pac-sudo.git ~/Projects/pac-sudo
ln -s ~/Projects/pac-sudo/pac_sudo.py ~/.local/bin/pac-sudo
```

If you already have this clone or launcher, reuse it instead of overwriting it.
Keep the `pac-sudo-askpass` symlink beside `pac_sudo.py`; sudo uses that helper
to request the password.

Add this block once to `~/.bashrc`:

```bash
# Pac-Sudo: animate successful sudo authentication in interactive Bash.
if [[ $- == *i* && -x "$HOME/.local/bin/pac-sudo" ]]; then
    source "$HOME/Projects/pac-sudo/shell.bash"
fi
```

If you clone to a different location, adjust both paths above to match it.

## Use

Open a new Kitty window, or reload the integration in an existing Bash shell:

```bash
source ~/.bashrc
sudo -k
sudo whoami
```

The two separate sudo commands discard the cached authentication and then run
a harmless command that prints `root`. Enter your password in your terminal.
Incorrect passwords use sudo's normal retry policy and never play the animation.
When sudo already remembers your authentication, no password is requested and
no animation plays.

Preview without entering any password or running sudo:

```bash
~/.local/bin/pac-sudo --demo
```

## How it works

The Bash function calls the Python program. It uses sudo's documented askpass
interface to run `sudo -A -v`, waits for successful authentication, animates the
masked stars, and runs the original command with `/usr/bin/sudo`. Sudo owns
password checking and retries. The program does not modify PAM, sudoers, Kitty,
or the system sudo binary.

The helper reads the password using Python's `getpass` with `echo_char="*"` and
sends it only through sudo's private askpass pipe. No password is saved to a
file, command line, environment variable, or log. A private temporary directory
holds only the most recently entered password's character count and is removed
after authentication. Python temporarily holds the password in memory, as any
password prompt must; it does not promise secure erasure of all Python copies.
All artwork goes directly to the terminal, leaving command input and output
available for pipes and redirects. Pac-Man takes about one second.

Normal commands, `sudo -v`, `-u`/`-g`, `-i`/`-s`, and common environment flags
are supported. Options that explicitly change input or caching (`-A`, `-S`,
`-n`, `-k`, `-K`, `-N`), listing/editing/custom prompt modes and unknown options
go directly to standard sudo, without animation. This preserves their behavior.
Use separate `sudo -k` and `sudo command` calls to force an animated prompt.
Commands without a foreground terminal also use standard sudo.

This wrapper is designed for a personal desktop with sudo's usual password
cache. A configuration with `timestamp_timeout=0`, command-specific password
rules, or passwordless commands mixed with password-protected commands may
request an extra password because validation is separate from command execution.
Use `command sudo ...` for those policies. Scripts and absolute `/usr/bin/sudo`
calls are not changed by the interactive Bash function.

Ctrl+C cancels password entry. Ctrl+Z during password entry or the animation
cancels that interaction so the terminal is never left with echo disabled.
Set `NO_COLOR=1` to omit the yellow color.

## Bypass or remove

Bypass the wrapper for one command:

```bash
command sudo whoami
```

Remove the function from the current shell:

```bash
unset -f sudo
```

To disable it permanently, remove the Pac-Sudo block at the end of `~/.bashrc`.

## Checks

```bash
cd ~/Projects/pac-sudo
python3 -m unittest discover -s tests -v
```

The integration checks use a fake sudo process and a pseudo-terminal. They
exercise accepted/rejected passwords, retries, cancellation, cached credentials,
streams and exit codes without needing an administrator password.

References: [sudo's askpass and validation interfaces](https://github.com/sudo-project/sudo/blob/main/docs/sudo.man.in)
and [Python getpass](https://docs.python.org/3/library/getpass.html).
