#!/usr/bin/python3 -I
"""Local test double. Never reads or validates a system password."""
import json
import os
from pathlib import Path
import subprocess
import sys

directory = Path(os.environ["FAKE_SUDO_DIR"])
arguments = sys.argv[1:]
if arguments[:2] == ["-A", "-v"]:
    (directory / "validation.json").write_text(json.dumps({"args": arguments, "parent": os.getppid()}))
    if os.environ.get("FAKE_SUDO_CACHED") == "1":
        raise SystemExit(0)
    for attempt in range(3):
        result = subprocess.run([os.environ["SUDO_ASKPASS"], "[sudo] password for test-user: "],
                                stdout=subprocess.PIPE)
        if result.returncode:
            raise SystemExit(1)
        if result.stdout == os.environ.get("FAKE_SUDO_EXPECTED", "test-only-secret").encode() + b"\n":
            raise SystemExit(0)
        print("Sorry, try again.", file=sys.stderr, flush=True)
    raise SystemExit(1)

(directory / "execution.json").write_text(json.dumps({"args": arguments, "parent": os.getppid()}))
if arguments == ["cat"]:
    sys.stdout.buffer.write(sys.stdin.buffer.read())
else:
    print("COMMAND_EXECUTED", flush=True)
raise SystemExit(int(os.environ.get("FAKE_SUDO_EXIT", "0")))
