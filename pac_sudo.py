#!/usr/bin/python3 -I
"""A terminal-only Pac-Man animation for successful sudo authentication."""

from __future__ import annotations

import base64
import contextlib
from dataclasses import dataclass
import getpass
import io
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

_ = None
K = (20, 20, 20)

# Ghost RGB
GC = (0, 220, 255)   # Cyan Inky body
GW = (255, 255, 255) # Eye white
GB = (0, 50, 220)    # Pupil blue

GHOST_1_GRID = [
    [_, _, GC, GC, GC, GC, _, _],
    [_, GC, GC, GC, GC, GC, GC, _],
    [GC, GW, GW, GC, GW, GW, GC, GC],
    [GC, GW, GB, GC, GW, GB, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [GC, _, GC, _, _, GC, _, GC],
]

GHOST_2_GRID = [
    [_, _, GC, GC, GC, GC, _, _],
    [_, GC, GC, GC, GC, GC, GC, _],
    [GC, GW, GW, GC, GW, GW, GC, GC],
    [GC, GW, GB, GC, GW, GB, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [GC, GC, GC, GC, GC, GC, GC, GC],
    [_, GC, _, GC, GC, _, GC, _],
]

# Invader RGB
IG = (50, 255, 50)

INVADER_1_GRID = [
    [_, _, IG, _, _, IG, _, _],
    [_, _, _, IG, IG, _, _, _],
    [_, _, IG, IG, IG, IG, _, _],
    [_, IG, IG, _, _, IG, IG, _],
    [IG, IG, IG, IG, IG, IG, IG, IG],
    [IG, _, IG, IG, IG, IG, _, IG],
    [IG, _, IG, _, _, IG, _, IG],
    [_, _, _, IG, IG, _, _, _],
]

INVADER_2_GRID = [
    [_, _, IG, _, _, IG, _, _],
    [IG, _, _, IG, IG, _, _, IG],
    [IG, _, IG, IG, IG, IG, _, IG],
    [IG, IG, IG, _, _, IG, IG, IG],
    [_, IG, IG, IG, IG, IG, IG, _],
    [_, _, IG, IG, IG, IG, _, _],
    [_, IG, _, _, _, _, IG, _],
    [IG, _, _, _, _, _, _, IG],
]

# Zelda / Link RGB
LG = (46, 180, 80)    # Kokiri Green hat & tunic
LY = (255, 215, 0)    # Gold Triforce / hair
LS = (255, 205, 160)  # Skin tone
LSW = (240, 245, 255) # Silver/White Master sword blade
LSB = (0, 160, 240)   # Blue Master sword hilt/crossguard
LST = (140, 150, 160) # Grey Pedestal Stone
LB = (140, 80, 40)    # Brown belt

LINK_GRIP_GRID = [
    [_, _, _, _, _, LY, LY, _, _, _, _, _],
    [_, _, _, _, LY, LY, LY, LY, _, _, _, _],
    [_, _, _, LG, LG, LG, LG, LG, _, _, _, _],
    [_, _, LG, LG, LS, K, LS, LY, LY, _, _, _],
    [_, _, LS, LSB, LSB, LSB, LSB, LS, _, _, _, _],
    [_, _, _, LG, LG, LB, LG, LG, _, _, _, _],
    [_, LST, LST, LST, LSW, LST, LST, LST, _, _, _, _],
    [LST, LST, LST, LST, LST, LST, LST, LST, LST, LST, _, _],
]

LINK_PULL_GRID = [
    [_, _, _, _, _, LY, LY, _, _, _, _, _],
    [_, _, _, _, LY, LY, LY, LY, _, _, _, _],
    [_, _, _, LG, LG, LG, LG, LG, _, _, _, _],
    [_, _, LG, LS, K, LS, K, LS, LY, _, _, _],
    [_, LS, LSB, LSB, LSW, LSB, LSB, LS, _, _, _, _],
    [_, _, _, LG, LG, LB, LG, LG, _, _, _, _],
    [_, LST, LST, LST, _, LST, LST, LST, _, _, _, _],
    [LST, LST, LST, LST, LST, LST, LST, LST, LST, LST, _, _],
]

LINK_DRAWN_GRID = [
    [_, _, LSW, LSW, LSW, LSW, LSW, LSW, _, _, _, _],
    [_, _, _, LSB, LSB, LSB, LSB, _, _, _, _, _],
    [_, _, LS, LG, LG, LG, LG, LS, _, _, _, _],
    [_, _, LG, LG, LS, K, LS, LY, LY, _, _, _],
    [_, _, _, LG, LG, LB, LG, LG, _, _, _, _],
    [_, _, _, LG, LG, LG, LG, LG, _, _, _, _],
    [_, LST, LST, LST, _, LST, LST, LST, _, _, _, _],
    [LST, LST, LST, LST, LST, LST, LST, LST, LST, LST, _, _],
]

def pixel_pair(top, bottom, no_color=False):
    if top is None and bottom is None:
        return " "
    if no_color:
        return "#"
    if top is not None and bottom is None:
        r, g, b = top
        return f"\x1b[38;2;{r};{g};{b}m▀{RESET}"
    if top is None and bottom is not None:
        r, g, b = bottom
        return f"\x1b[38;2;{r};{g};{b}m▄{RESET}"
    r1, g1, b1 = top
    r2, g2, b2 = bottom
    return f"\x1b[38;2;{r1};{g1};{b1}m\x1b[48;2;{r2};{g2};{b2}m▀{RESET}"

def render_grid(grid, no_color=False):
    height = len(grid)
    width = len(grid[0])
    lines = []
    for y in range(0, height, 2):
        row_chars = []
        for x in range(width):
            top = grid[y][x]
            bottom = grid[y + 1][x] if y + 1 < height else None
            row_chars.append(pixel_pair(top, bottom, no_color=no_color))
        lines.append("".join(row_chars))
    return lines

PACMAN_THEME = {
    "name": "pacman",
    "open": (" .---. ", "/ o.-' ", "\\  '-. ", " '---' "),
    "closed": (" .---. ", "/ o  \\ ", "\\    / ", " '---' "),
    "color": YELLOW,
    "pellet": "*",
}

KIRBY_THEME = {
    "name": "kirby",
    "open": ("        ", " (>'.')>", " (____) ", "  '' '' "),
    "closed": ("        ", " (<'.'o)", " (____) ", "  '' '' "),
    "color": MAGENTA,
    "pellet": "★",
}

SONIC_THEME = {
    "name": "sonic",
    "open": ("  .---.  ", " / @@@ \\ ", " \\ @@@ / ", "  '---'  "),
    "closed": ("  .---.  ", " / ### \\ ", " \\ ### / ", "  '---'  "),
    "color": CYAN,
    "pellet": "o",
}

GOOSE_THEME = {
    "name": "goose",
    "open": ("  >(o )___ ", "   ( ._> / ", "    `---'  ", "     / |   "),
    "closed": ("  >(o )___ ", "   ( ._> / ", "    `---'  ", "     | \\   "),
    "color": WHITE,
    "pellet": "honk!",
}

MAGE_THEME = {
    "name": "mage",
    "open": ("   /\\    ", "  |* *|  ", "  /|_|\\  ", "   ' '   "),
    "closed": ("   /\\    ", "  |o o|  ", "  /|_|\\  ", "   ' '   "),
    "color": YELLOW,
    "pellet": "🔥",
}

NYAN_THEME = {
    "name": "nyan",
    "open": (" +_,-._+ ", " |[:::'] ", " |[::: ] ", "  -   -  "),
    "closed": ("  +_,-.+ ", " |[::: ] ", " |[:::'] ", "   - -   "),
    "color": MAGENTA,
    "pellet": "≈",
}

GHOST_THEME = {
    "name": "ghost",
    "open_grid": GHOST_1_GRID,
    "closed_grid": GHOST_2_GRID,
    "pellet": "o",
}

ALIEN_THEME = {
    "name": "alien",
    "open_grid": INVADER_1_GRID,
    "closed_grid": INVADER_2_GRID,
    "pellet": "▪",
}

def generate_alohomora_frames():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []

    frames = []
    GOLD = (218, 165, 32)
    GOLD_HIGHLIGHT = (255, 215, 0)
    DARK = (30, 30, 30)
    SILVER = (192, 192, 192)
    CYAN_SPARK = (120, 220, 255)
    WHITE_GLOW = (255, 255, 255)
    WAND_WOOD = (139, 69, 19)

    for step in range(7):
        img = Image.new("RGBA", (130, 80), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Wand entering from left
        wand_x = 10 + step * 4
        wand_y = 45 - step
        d.line([(wand_x - 30, wand_y + 15), (wand_x, wand_y)], fill=WAND_WOOD, width=3)

        # Lock body
        lx, ly = 70, 38
        d.rectangle([lx, ly, lx + 36, ly + 32], fill=GOLD, outline=GOLD_HIGHLIGHT, width=2)
        # Keyhole
        d.ellipse([lx + 15, ly + 10, lx + 21, ly + 16], fill=DARK)
        d.polygon([(lx + 16, ly + 14), (lx + 20, ly + 14), (lx + 22, ly + 24), (lx + 14, ly + 24)], fill=DARK)

        if step < 4:
            # Locked shackle
            d.arc([lx + 6, ly - 20, lx + 30, ly + 8], 180, 0, fill=SILVER, width=5)
            if step >= 2:
                # Magic sparks from wand tip
                for offset in [(-3, -4), (4, -2), (2, 5), (-2, 6)]:
                    d.point((wand_x + offset[0] + 5, wand_y + offset[1]), fill=CYAN_SPARK)
        else:
            # Shackle popping up and swinging open!
            lift = (step - 3) * 4
            d.arc([lx + 2, ly - 24 - lift, lx + 26, ly + 4 - lift], 160, 340, fill=WHITE_GLOW, width=5)
            # Magic burst
            burst_r = (step - 3) * 6
            d.ellipse([lx + 18 - burst_r, ly + 14 - burst_r, lx + 18 + burst_r, ly + 14 + burst_r],
                      outline=CYAN_SPARK, width=2)
            d.text((lx - 20, 5), "Alohomora!", fill=CYAN_SPARK)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames


def kitty_image_escape(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    chunks = []
    chunk_size = 4096
    for i in range(0, len(b64), chunk_size):
        chunk = b64[i : i + chunk_size]
        is_last = (i + chunk_size) >= len(b64)
        m = 0 if is_last else 1
        if i == 0:
            chunks.append(f"\x1b_Gf=100,a=T,m={m};{chunk}\x1b\\")
        else:
            chunks.append(f"\x1b_Gm={m};{chunk}\x1b\\")
    return "".join(chunks)


ALOHOMORA_FRAMES = generate_alohomora_frames()

ALOHOMORA_THEME = {
    "name": "alohomora",
    "special": "kitty_image",
}

ZELDA_THEME = {
    "name": "zelda",
    "special": "master_sword",
}

THEMES = [
    PACMAN_THEME,
    KIRBY_THEME,
    SONIC_THEME,
    GOOSE_THEME,
    MAGE_THEME,
    NYAN_THEME,
    GHOST_THEME,
    ALIEN_THEME,
    ZELDA_THEME,
]
if ALOHOMORA_FRAMES:
    THEMES.append(ALOHOMORA_THEME)


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
        if chosen.get("name") == "alohomora" and ALOHOMORA_FRAMES:
            steps = len(ALOHOMORA_FRAMES)
            delay = duration / steps
            for step, frame in enumerate(ALOHOMORA_FRAMES):
                escape = kitty_image_escape(frame)
                tty.write("\x1b[4A")
                tty.write("\r\x1b[2K" + escape + "\n")
                tty.write("\r\x1b[2K" + "\n")
                tty.write("\r\x1b[2K" + "\n")
                tty.write("\r\x1b[2K" + "\n")
                tty.flush()
                time.sleep(delay)
            return

        if chosen.get("name") == "zelda":
            steps = count + 1
            delay = duration / steps
            c_yellow = "" if no_color else YELLOW
            c_cyan = "" if no_color else CYAN

            for step in range(steps):
                progress = step / max(1, count)
                pellets = "•" * max(0, count - step)
                if progress < 0.45:
                    grid = LINK_GRIP_GRID
                    msg = c_yellow + pellets + RESET
                elif progress < 0.85:
                    grid = LINK_PULL_GRID
                    msg = c_yellow + pellets + RESET
                else:
                    grid = LINK_DRAWN_GRID
                    msg = c_yellow + " ✦ " + c_cyan + "Master Sword!" + RESET

                lines = render_grid(grid, no_color=no_color)
                # Attach pellets/message to row 1
                lines[1] = lines[1] + "  " + msg

                tty.write("\x1b[4A")
                for row_text in lines:
                    tty.write("\r\x1b[2K" + row_text + "\n")
                tty.flush()
                time.sleep(delay)
            return

        pellet_char = chosen.get("pellet", "*")
        if "open_grid" in chosen:
            open_lines = render_grid(chosen["open_grid"], no_color=no_color)
            closed_lines = render_grid(chosen["closed_grid"], no_color=no_color)
            for step in range(count + 1):
                sprite_lines = open_lines if step % 2 == 0 else closed_lines
                tty.write("\x1b[4A")
                for row, line in enumerate(sprite_lines):
                    pellets = pellet_char * (count - step) if row == 1 else ""
                    tty.write("\r\x1b[2K" + " " * step + line + " " + pellets + "\n")
                tty.flush()
                time.sleep(duration / (count + 1))
        else:
            # Classic ASCII sprites (e.g. Pacman)
            color = "" if no_color else chosen["color"]
            reset = RESET if color else ""
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
    if arguments and arguments[0] == "--demo":
        tty = terminal()
        if tty is None:
            print("pac-sudo: open a terminal to see the demo.", file=sys.stderr)
            return 1
        theme_name = arguments[1] if len(arguments) > 1 else None
        chosen_theme = None
        if theme_name:
            for t in THEMES:
                if t["name"].lower() == theme_name.lower():
                    chosen_theme = t
                    break
            if not chosen_theme:
                print(f"pac-sudo: unknown theme '{theme_name}'. Available: {', '.join(t['name'] for t in THEMES)}", file=sys.stderr)
                return 1
        with tty, cancel_on_signals():
            theme_display = chosen_theme['name'] if chosen_theme else 'Random'
            tty.write(f"Demo ({theme_display}): Pac-Sudo animation.\n")
            animate(tty, 12, theme=chosen_theme)
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
