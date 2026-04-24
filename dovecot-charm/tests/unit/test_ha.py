# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from exceptions import HASetupError
from ha import _validate_cron_schedule


class TestValidateCronSchedule:
    def test_valid_standard_schedule(self):
        assert _validate_cron_schedule("*/30 * * * *") == "*/30 * * * *"

    def test_valid_every_minute(self):
        assert _validate_cron_schedule("*/1 * * * *") == "*/1 * * * *"

    def test_valid_specific_fields(self):
        assert _validate_cron_schedule("0 4 * * 1") == "0 4 * * 1"

    def test_rejects_newline_in_schedule(self):
        with pytest.raises(HASetupError, match="must not contain newlines"):
            _validate_cron_schedule("*/30 * * * *\nbadline root /bin/evil")

    def test_rejects_carriage_return(self):
        with pytest.raises(HASetupError, match="must not contain newlines"):
            _validate_cron_schedule("*/30 * * * *\r")

    def test_rejects_too_few_fields(self):
        with pytest.raises(HASetupError, match="expected 5 fields, got 4"):
            _validate_cron_schedule("*/30 * * *")

    def test_rejects_too_many_fields(self):
        with pytest.raises(HASetupError, match="expected 5 fields, got 6"):
            _validate_cron_schedule("*/30 * * * * extra")

    def test_rejects_empty_string(self):
        with pytest.raises(HASetupError, match="expected 5 fields, got 0"):
            _validate_cron_schedule("")

    def test_rejects_command_substitution(self):
        with pytest.raises(HASetupError, match="disallowed characters"):
            _validate_cron_schedule("$(rm) * * * *")

    def test_rejects_backticks(self):
        with pytest.raises(HASetupError, match="disallowed characters"):
            _validate_cron_schedule("`id` * * * *")

    def test_rejects_semicolon(self):
        with pytest.raises(HASetupError, match="disallowed characters"):
            _validate_cron_schedule("*;id * * * *")

    def test_rejects_pipe(self):
        with pytest.raises(HASetupError, match="disallowed characters"):
            _validate_cron_schedule("*|cat * * * *")

    def test_rejects_alphabetic_field(self):
        with pytest.raises(HASetupError, match="disallowed characters"):
            _validate_cron_schedule("* * * * MON")

    def test_normalises_whitespace(self):
        assert _validate_cron_schedule("*/30  *   *  * *") == "*/30 * * * *"
