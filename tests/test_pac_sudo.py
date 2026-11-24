import contextlib
import errno
import io
import json
import os
from pathlib import Path
import pty
import select
import signal
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pac_sudo


class ArgumentTests(unittest.TestCase):
    def test_preserves_command_arguments_and_context(self):
        for args, context in [
            (["whoami"], []),
            (["-EHu", "root", "printf", "-n"], ["-u", "root"]),
            (["-uroot", "-g", "wheel", "whoami"], ["-u", "root", "-g", "wheel"]),
            (["--user=root", "--group", "wheel", "whoami"], ["-u", "root", "-g", "wheel"]),
            (["--preserve-env=HOME", "whoami"], []),
            (["--", "echo", "-S"], []),
            (["NAME=hello world", "env"], []),
            (["-i"], []), (["-s"], []),
        ]:
            with self.subTest(args=args):
                parsed = pac_sudo.classify(args)
                self.assertEqual(parsed.arguments, args)
                self.assertEqual(parsed.context, context)

    def test_special_modes_and_unknown_options_are_delegated(self):
        for args in [[], ["-k"], ["-k", "whoami"], ["-kv"], ["-K"],
                     ["-S", "cat"], ["-A", "whoami"], ["-n", "whoami"],
                     ["-N", "whoami"], ["-l"], ["-e", "/tmp/example"],
                     ["-V"], ["-h"], ["--help"], ["-p", "Password: ", "whoami"],
                     ["--not-an-option"], ["-u"], ["--user="], ["-is"],
                     ["-v", "whoami"], ["-Ev"], ["--"]]:
            with self.subTest(args=args):
                self.assertIsNone(pac_sudo.classify(args))

    def test_validate_only(self):
        parsed = pac_sudo.classify(["-u", "root", "-v"])
        self.assertTrue(parsed.validate_only)
        self.assertEqual(parsed.context, ["-u", "root"])


class MemoryTerminal(io.StringIO):
    def fileno(self):
        return 2


class AnimationTests(unittest.TestCase):
    def test_cursor_is_restored_when_interrupted(self):
        tty = MemoryTerminal()
        with patch.object(pac_sudo.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                pac_sudo.animate(tty, 12)
        self.assertTrue(tty.getvalue().endswith("\x1b[?25h"))

    def test_narrow_terminal_has_no_wrapped_animation(self):
        tty = MemoryTerminal()
        with patch.object(pac_sudo.os, "get_terminal_size", return_value=os.terminal_size((10, 24))):
            pac_sudo.animate(tty, 500, duration=0)
        self.assertEqual(tty.getvalue(), "C *  OK\n")

    def test_long_password_is_bounded_by_terminal_width(self):
        tty = MemoryTerminal()
        with patch.object(pac_sudo.os, "get_terminal_size", return_value=os.terminal_size((20, 24))):
            pac_sudo.animate(tty, 1000, duration=0)
        self.assertNotIn("*" * 11, tty.getvalue())


class TerminalTests(unittest.TestCase):
    def exercise(self, arguments, responses=(), environment=None, redirected=False):
        """Run the real helper on a real PTY, talking only to fake sudo."""
        with tempfile.TemporaryDirectory(prefix="pac-sudo-test-") as temporary:
            directory = Path(temporary)
            (directory / "stdin").write_bytes(b"piped input\nwith a second line\n")
            pid, master = pty.fork()
            if pid == 0:
                try:
                    termios.tcsetwinsize(0, (24, 80))
                    # A real shell keeps its terminal open while the child's
                    # standard streams are redirected. Emulate that here.
                    terminal_keepalive = os.dup(0)
                    os.environ.update({"TERM": "xterm-kitty", "FAKE_SUDO_DIR": temporary})
                    for key in ("FAKE_SUDO_CACHED", "FAKE_SUDO_EXIT", "FAKE_SUDO_EXPECTED",
                                "PAC_SUDO_DISABLE"):
                        os.environ.pop(key, None)
                    os.environ.update(environment or {})
                    if redirected:
                        for descriptor, filename, mode in [(0, "stdin", "rb"), (1, "stdout", "wb"), (2, "stderr", "wb")]:
                            with open(directory / filename, mode) as file:
                                os.dup2(file.fileno(), descriptor)
                    pac_sudo.SUDO = str(ROOT / "tests" / "fake_sudo.py")
                    # Keep tests usable if a test runner happens to be root.
                    with patch.object(pac_sudo.os, "geteuid", return_value=1000):
                        result = pac_sudo.main(arguments)
                except KeyboardInterrupt:
                    result = 130
                except BaseException:
                    import traceback
                    traceback.print_exc()
                    result = 99
                os._exit(result)
            output = bytearray()
            pending = iter(responses)
            prompt_count = 0
            deadline = time.monotonic() + 12
            status = None
            terminal_closed = False
            try:
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([] if terminal_closed else [master], [], [], 0.05)
                    if readable:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError as error:
                            if error.errno == errno.EIO:
                                terminal_closed = True
                                continue
                            raise
                        if not chunk:
                            terminal_closed = True
                            continue
                        output.extend(chunk)
                        observed = output.count(b"[sudo] password for test-user: ")
                        while prompt_count < observed:
                            prompt_count += 1
                            response = next(pending, None)
                            if response is not None:
                                os.write(master, response)
                    ended, candidate = os.waitpid(pid, os.WNOHANG)
                    if ended:
                        status = candidate
                        # Drain the final terminal output after process exit.
                        while select.select([master], [], [], 0)[0]:
                            try:
                                chunk = os.read(master, 65536)
                            except OSError:
                                break
                            if not chunk:
                                break
                            output.extend(chunk)
                        break
                if status is None:
                    ended, candidate = os.waitpid(pid, os.WNOHANG)
                    if not ended:
                        self.fail("terminal test timed out: " + repr(bytes(output)))
                    status = candidate
                echo = bool(termios.tcgetattr(master)[3] & termios.ECHO)
                files = {file.name: file.read_bytes() for file in directory.iterdir()}
                return os.waitstatus_to_exitcode(status), bytes(output), files, echo
            finally:
                if status is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(pid, signal.SIGKILL)
                    with contextlib.suppress(ChildProcessError):
                        os.waitpid(pid, 0)
                os.close(master)

    def assertAnimated(self, output):
        sprites = [b" .---. ", b"(o o)", b"|o.o|", b"[==|T|==]"]
        self.assertTrue(any(s in output for s in sprites), f"No animation sprite found in output: {repr(output)}")

    def test_success_animates_before_running_original_command(self):
        code, output, files, echo = self.exercise(["whoami"], [b"test-only-secret\n"])
        self.assertEqual(code, 0)
        self.assertAnimated(output)
        first_sprite_index = min(output.index(s) for s in [b" .---. ", b"(o o)", b"|o.o|", b"[==|T|==]"] if s in output)
        self.assertLess(first_sprite_index, output.index(b"COMMAND_EXECUTED"))
        self.assertNotIn(b"test-only-secret", output)
        self.assertEqual(json.loads(files["execution.json"])["args"], ["whoami"])
        self.assertEqual(json.loads(files["execution.json"])["parent"], json.loads(files["validation.json"])["parent"])
        self.assertTrue(echo)

    def test_three_rejected_passwords_never_animate_or_run_command(self):
        code, output, files, echo = self.exercise(["whoami"], [b"wrong-value\n"] * 3)
        self.assertEqual(code, 1)
        for s in [b" .---. ", b"(o o)", b"|o.o|", b"[==|T|==]"]:
            self.assertNotIn(s, output)
        self.assertNotIn("execution.json", files)
        self.assertNotIn(b"wrong-value", output)
        self.assertEqual(output.count(b"Sorry, try again."), 3)
        self.assertTrue(echo)

    def test_retry_then_success(self):
        code, output, files, echo = self.exercise(["whoami"], [b"wrong-value\n", b"test-only-secret\n"])
        self.assertEqual(code, 0)
        self.assertIn(b"Sorry, try again.", output)
        self.assertAnimated(output)
        self.assertTrue(echo)

    def test_cached_authentication_animates_by_default(self):
        code, output, files, echo = self.exercise(["whoami"], environment={"FAKE_SUDO_CACHED": "1"})
        self.assertEqual(code, 0)
        self.assertAnimated(output)
        self.assertIn(b"COMMAND_EXECUTED", output)

    def test_cached_authentication_can_be_disabled(self):
        code, output, files, echo = self.exercise(["whoami"], environment={
            "FAKE_SUDO_CACHED": "1",
            "PAC_SUDO_NO_CACHED_ANIMATION": "1",
        })
        self.assertEqual(code, 0)
        self.assertEqual(output, b"COMMAND_EXECUTED\r\n")

    def test_validation_does_not_execute_a_command(self):
        code, output, files, echo = self.exercise(["-v"], [b"test-only-secret\n"])
        self.assertEqual(code, 0)
        self.assertAnimated(output)
        self.assertNotIn("execution.json", files)

    def test_failed_command_still_animates_after_successful_password(self):
        code, output, files, echo = self.exercise(["false"], [b"test-only-secret\n"], {"FAKE_SUDO_EXIT": "37"})
        self.assertEqual(code, 37)
        self.assertAnimated(output)

    def test_pipes_and_redirects_are_preserved(self):
        code, output, files, echo = self.exercise(["cat"], [b"test-only-secret\n"], redirected=True)
        self.assertEqual(code, 0)
        self.assertEqual(files["stdout"], files["stdin"])
        self.assertEqual(files["stderr"], b"")
        self.assertAnimated(output)
        self.assertNotIn(b"test-only-secret", b"".join(files.values()) + output)

    def test_ctrl_c_restores_echo_and_never_runs_command(self):
        code, output, files, echo = self.exercise(["whoami"], [b"\x03"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("execution.json", files)
        for s in [b" .---. ", b"(o o)", b"|o.o|", b"[==|T|==]"]:
            self.assertNotIn(s, output)
        self.assertTrue(echo)

    def test_backspace_and_utf8_password(self):
        code, output, files, echo = self.exercise(["whoami"], ["test-pässX".encode() + b"\x7f\n"],
                                                 {"FAKE_SUDO_EXPECTED": "test-päss"})
        self.assertEqual(code, 0)
        self.assertNotIn("test-päss".encode(), output)
        self.assertTrue(echo)

    def test_explicit_noninteractive_mode_is_not_prevalidated(self):
        code, output, files, echo = self.exercise(["-n", "whoami"])
        self.assertEqual(code, 0)
        self.assertNotIn("validation.json", files)
        self.assertEqual(json.loads(files["execution.json"])["args"], ["-n", "whoami"])


if __name__ == "__main__":
    unittest.main()
