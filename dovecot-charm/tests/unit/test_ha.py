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
