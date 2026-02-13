"""Tests for the scan CLI command."""

import pytest
from click.testing import CliRunner

from garde.cli import main


class TestScanSourceFilter:
    """Tests for the --source filter option."""

    # When --source is provided, help should show available choices
    def test_source_option_in_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ['scan', '--help'])

        assert result.exit_code == 0
        assert '--source' in result.output
        assert 'claude_code' in result.output
        assert 'handoffs' in result.output

    # When --source handoffs is used, output should mention scanning handoffs
    def test_source_filter_handoffs(self):
        runner = CliRunner()
        # This will actually try to scan, but we're just checking the output format
        result = runner.invoke(main, ['scan', '--source', 'handoffs', '--dry-run'])

        # Should skip other source types
        assert 'Skipping Claude Code' in result.output or 'Scanning handoff' in result.output

    # When --source is invalid, should show error with valid choices
    def test_invalid_source_filter(self):
        runner = CliRunner()
        result = runner.invoke(main, ['scan', '--source', 'invalid'])

        assert result.exit_code != 0
        assert 'Invalid value' in result.output or 'invalid' in result.output.lower()
