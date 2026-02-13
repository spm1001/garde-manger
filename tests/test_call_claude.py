"""Tests for _call_claude CLI wrapper."""

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from garde.llm import _call_claude, MODEL


def _make_result(stdout="", stderr="", returncode=0):
    """Create a mock subprocess.CompletedProcess."""
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class TestCallClaude:
    def test_happy_path(self):
        output = json.dumps({"type": "result", "result": "hello world"})
        mock_result = _make_result(stdout=output)

        with patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run", return_value=mock_result) as mock_run:
            text = _call_claude("say hello")

        assert text == "hello world"
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0][0] == "claude"
        assert "-p" in args[0][0]
        assert "--no-session-persistence" in args[0][0]
        assert args[1]["input"] == "say hello"

    def test_cli_not_found(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="claude CLI not found"):
                _call_claude("test")

    def test_nonzero_exit(self):
        mock_result = _make_result(returncode=1, stderr="something went wrong")

        with patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="claude CLI failed"):
                _call_claude("test")

    def test_timeout(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 120)):
            with pytest.raises(RuntimeError, match="timed out"):
                _call_claude("test")

    def test_bad_json_output(self):
        mock_result = _make_result(stdout="not json at all")

        with patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Failed to parse"):
                _call_claude("test")

    def test_missing_result_key(self):
        output = json.dumps({"type": "error", "message": "oops"})
        mock_result = _make_result(stdout=output)

        with patch("shutil.which", return_value="/usr/local/bin/claude"), \
             patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Failed to parse"):
                _call_claude("test")

    def test_model_constant(self):
        assert MODEL == "claude-opus-4-6"
