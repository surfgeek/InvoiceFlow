"""Verify that bootstrap work remains visibly active during silent subprocess startup."""

import contextlib
import io
import subprocess
import unittest
from unittest.mock import Mock, patch

import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_silent_command_prints_heartbeat(self):
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired("command", 1), 0]
        output = io.StringIO()

        with patch("bootstrap.subprocess.Popen", return_value=process) as popen, \
                contextlib.redirect_stdout(output):
            bootstrap.run_visible(["command"], "failed")

        popen.assert_called_once_with(["command"], start_new_session=True)
        self.assertIn("Setup is active (1s elapsed)", output.getvalue())

    def test_failed_command_has_concise_setup_error(self):
        process = Mock()
        process.wait.return_value = 1
        with patch("bootstrap.subprocess.Popen", return_value=process), \
                self.assertRaisesRegex(SystemExit, "Could not install"):
            bootstrap.run_visible(["command"], "Could not install dependencies.")


if __name__ == "__main__":
    unittest.main()
