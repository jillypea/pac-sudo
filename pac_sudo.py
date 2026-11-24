#!/usr/bin/python3 -I
"""A terminal-only Pac-Man animation for successful sudo authentication."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import random
import signal
import stat
import subprocess
import sys
import tempfile
import time
import warnings


SUDO = "/usr/bin/sudo"
HERE = Path(__file__).resolve().parent
ASKPASS = HERE / "pac-sudo-askpass"
STATE_ENV = "PAC_SUDO_PROMPT_STATE"
RESET = "\x1b[0m"
YELLOW = "\x1b[93m"
CYAN = "\x1b[96m"
GREEN = "\x1b[92m"
MAGENTA = "\x1b[95m"
WHITE = "\x1b[97m"

PACMAN_THEME = {
    "name": "pacman",
    "open": (" .---. ", "/ o.-' ", "\\  '-. ", " '---' "),
    "closed": (" .---. ", "/ o  \\ ", "\\    / ", " '---' "),
    "color": YELLOW,
    "pellet": "*",
}

GHOST_THEME = {
    "name": "ghost",
    "open": ("  .-.  ", " (o o) ", " | ~ | ", " '~~'' "),
    "closed": ("  .-.  ", " (o o) ", " | ~ | ", " ''~~' "),
    "color": CYAN,
    "pellet": "o",
}

ALIEN_THEME = {
    "name": "alien",
    "open": ("  /_\\  ", " |o.o| ", " \\_-_/ ", "  ' '  "),
    "closed": ("  /_\\  ", " |o.o| ", " /---\\ ", "  ^ ^  "),
    "color": GREEN,
    "pellet": ".",
}

ZELDA_THEME = {
    "name": "zelda",
    "special": "master_sword",
}

THEMES = [PACMAN_THEME, GHOST_THEME, ALIEN_THEME, ZELDA_THEME]


@dataclass
class Invocation:
    arguments: list[str]
    context: list[str]
    validate_only: bool = False


def classify(arguments: list[str]) -> Invocation | None:
    """Recognize ordinary sudo calls; delegate other syntax unchanged.

    In particular, never reinterpret -k, -K, -N, -S, -A or -n. Those flags
    deliberately change caching/input semantics. Stop parsing at the command
    so that, for example, `sudo printf -n` is handled correctly.
    """
    context: list[str] = []
    flags: set[str] = set()
    index = 0
    command = False
    simple = {
        "--background": "b", "--preserve-env": "E", "--set-home": "H",
        "--login": "i", "--shell": "s", "--preserve-groups": "P",
        "--validate": "v",
    }
    valued = {"--user": "u", "--group": "g"}
    while index < len(arguments):
        arg = arguments[index]
        if arg == "--":
            command = index + 1 < len(arguments)
            break
        if not arg.startswith("-") or arg == "-":
            command = True
            break
        if arg.startswith("--"):
            key, separator, value = arg.partition("=")
            if key in valued:
                if not separator:
                    index += 1
                    if index >= len(arguments):
                        return None
                    value = arguments[index]
                if not value:
                    return None
                context.extend(["-" + valued[key], value])
            elif key == "--preserve-env" and separator:
                flags.add("E")
            elif key in simple and not separator:
                flags.add(simple[key])
            else:
                return None
        else:
            offset = 1
            while offset < len(arg):
                flag = arg[offset]
                if flag in "ug":
                    value = arg[offset + 1:]
                    if not value:
                        index += 1
                        if index >= len(arguments):
                            return None
                        value = arguments[index]
                    context.extend(["-" + flag, value])
                    break
                if flag not in "bEHisPv":
                    return None
                flags.add(flag)
                offset += 1
        index += 1
    if "v" in flags:
        if command or flags != {"v"}:
            return None
        return Invocation(arguments, context, validate_only=True)
    if "i" in flags and "s" in flags:
        return None
    if not command and not flags.intersection({"i", "s"}):
        return None
    return Invocation(arguments, context)


@contextlib.contextmanager
def cancel_on_signals():
    """Unwind getpass/animation cleanup even on hangup or Ctrl+Z."""
    def cancel(signum, _frame):
        raise KeyboardInterrupt

    saved = {}
    try:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGTSTP):
            saved[signum] = signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


def terminal():
    """Open the actual terminal without consuming a command's piped stdin."""
    try:
        tty = open("/dev/tty", "w", encoding="utf-8", buffering=1)
        if os.tcgetpgrp(tty.fileno()) != os.getpgrp():
            tty.close()
            return None
        return tty
    except (OSError, ValueError):
        return None


def askpass(prompt: str) -> int:
    """sudo's helper: its stdout is the private password pipe to sudo."""
    state = os.environ.get(STATE_ENV)
    if not state or not stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode):
        print("pac-sudo: this helper is only for sudo's private password pipe.", file=sys.stderr)
        return 1
    tty = terminal()
    if tty is None:
        return 1
    try:
        with tty, cancel_on_signals(), warnings.catch_warnings():
            # Never permit getpass's fallback to an echoing stdin prompt.
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass(prompt, stream=tty, echo_char="*")
            # Only the mask length is written to this private temporary file.
            # Passwords never go into files, argv, environment variables or logs.
            Path(state).write_text(str(len(password)), encoding="ascii")
            payload = bytearray(password, "utf-8")
            del password
            try:
                payload.append(10)
                view = memoryview(payload)
                while view:
                    written = os.write(sys.stdout.fileno(), view)
                    view = view[written:]
            finally:
                payload[:] = b"\0" * len(payload)
        return 0
    except (KeyboardInterrupt, EOFError, OSError, getpass.GetPassWarning):
        return 1


def animate(tty, length: int, duration: float = 1.05, theme: dict | None = None) -> None:
    """Draw only to /dev/tty, never to a sudo command's stdout/stderr."""
    try:
        columns = os.get_terminal_size(tty.fileno()).columns or 80
    except OSError:
        columns = 80
    count = min(max(1, length), max(1, columns - 10), 48)
    chosen = theme or random.choice(THEMES)
    no_color = "NO_COLOR" in os.environ

    if columns < 14:
        tty.write("C *  OK\n")
        tty.flush()
        return

    tty.write("\x1b[?25l" + "\n" * 4)
    tty.flush()
    try:
        if chosen.get("name") == "zelda":
            steps = count + 1
            delay = duration / steps
            for step in range(steps):
                progress = step / max(1, count)
                pellets = "*" * max(0, count - step)
                c_yellow = "" if no_color else YELLOW
                c_green = "" if no_color else GREEN
                c_cyan = "" if no_color else CYAN
                c_white = "" if no_color else WHITE
                c_reset = "" if no_color else RESET

                if progress < 0.45:
                    wiggle = "/" if step % 2 == 0 else "\\"
                    lines = [
                        c_yellow + "       ▲       " + c_reset,
                        c_green + f"     {wiggle}<'.)/    " + c_reset + c_yellow + pellets + c_reset,
                        c_cyan + "     |=|=      " + c_reset,
                        c_white + "   [==|T|==]   " + c_reset,
                    ]
                elif progress < 0.85:
                    wiggle = "\\" if step % 2 == 0 else "/"
                    lines = [
                        c_cyan + "      /|\\      " + c_reset,
                        c_green + f"    {wiggle}<'.'o{wiggle}   " + c_reset + c_yellow + pellets + c_reset,
                        c_cyan + "     |===|     " + c_reset,
                        c_white + "   [==|T|==]   " + c_reset,
                    ]
                else:
                    flash = c_cyan if step % 2 == 0 else c_yellow
                    lines = [
                        flash + "   --<{===+==> " + c_reset,
                        c_green + "    \\<'.')/    " + c_reset + c_yellow + " ✦ " + c_cyan + "Master Sword!" + c_reset,
                        c_green + "      |_|      " + c_reset,
                        c_white + "   [===T===]   " + c_reset,
                    ]

                tty.write("\x1b[4A")
                for row_text in lines:
                    tty.write("\r\x1b[2K" + row_text + "\n")
                tty.flush()
                time.sleep(delay)
            return

        color = "" if no_color else chosen["color"]
        reset = RESET if color else ""
        pellet_char = chosen.get("pellet", "*")
        open_sprite = chosen["open"]
        closed_sprite = chosen["closed"]

        for step in range(count + 1):
            sprite = open_sprite if step % 2 == 0 else closed_sprite
            tty.write("\x1b[4A")
            for row, shape in enumerate(sprite):
                pellets = pellet_char * (count - step) if row == 1 else ""
                tty.write("\r\x1b[2K" + " " * step + color + shape + reset + pellets + "\n")
            tty.flush()
            time.sleep(duration / (count + 1))
    finally:
        tty.write(RESET + "\x1b[?25h")
        tty.flush()


def wait_for(child: subprocess.Popen) -> int:
    # The terminal delivers Ctrl+C to both processes. Let sudo forward it to
    # the command and report the real exit status, without a Python traceback.
    while True:
        try:
            code = child.wait()
            return code if code >= 0 else 128 - code
        except KeyboardInterrupt:
            continue


def run(invocation: Invocation, tty) -> int:
    with tempfile.TemporaryDirectory(prefix="pac-sudo-") as directory:
        state = Path(directory) / "mask-length"
        environment = os.environ.copy()
        environment["SUDO_ASKPASS"] = str(ASKPASS)
        environment[STATE_ENV] = str(state)
        # One sudo process owns all retries and the system's authentication
        # policy. A second invocation runs only after validation succeeds.
        child = subprocess.Popen([SUDO, "-A", "-v", *invocation.context], env=environment)
        result = wait_for(child)
        if result:
            return result
        if state.exists():
            length = int(state.read_text(encoding="ascii"))
            with cancel_on_signals():
                animate(tty, length)
        elif not os.environ.get("PAC_SUDO_NO_CACHED_ANIMATION"):
            # Credentials were valid from cache; show quick sprint animation (~0.35s).
            with cancel_on_signals():
                animate(tty, length=8, duration=0.35)
    if invocation.validate_only:
        return 0
    # Keep the same parent PID for validation and execution: sudo can use a
    # parent-PID timestamp as well as a terminal timestamp. Inherit all three
    # original streams so pipes, redirects and interactive programs work.
    return wait_for(subprocess.Popen([SUDO, *invocation.arguments]))


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if Path(sys.argv[0]).name == "pac-sudo-askpass":
        return askpass(arguments[0] if arguments else "[sudo] Password: ")
    if arguments == ["--demo"]:
        tty = terminal()
        if tty is None:
            print("pac-sudo: open a terminal to see the demo.", file=sys.stderr)
            return 1
        with tty, cancel_on_signals():
            tty.write("Demo: Pac-Man eats masked password stars.\n")
            animate(tty, 12)
        return 0
    if arguments == ["--pacman-help"]:
        print("Use sudo normally. Demo: pac-sudo --demo\n"
              "Bypass: command sudo ...\n"
              "Fresh prompt: sudo -k, then sudo whoami\n"
              "Source and details: " + str(HERE / "README.md"))
        return 0
    invocation = classify(arguments)
    if (invocation is None or os.geteuid() == 0
            or os.environ.get("PAC_SUDO_DISABLE") == "1"
            or os.environ.get("TERM", "dumb") == "dumb"):
        os.execv(SUDO, [SUDO, *arguments])
    tty = terminal()
    if tty is None:
        os.execv(SUDO, [SUDO, *arguments])
    with tty:
        return run(invocation, tty)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except OSError as error:
        print(f"pac-sudo: {error}", file=sys.stderr)
        raise SystemExit(1)
