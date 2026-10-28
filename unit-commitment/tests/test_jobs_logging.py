"""Tests for the log output of the job worker (what shows up in the Azure log stream)."""
import logging

import pytest

from solver.jobs import run_solve


def test_run_solve_logs_start_and_finish(caplog):
    with caplog.at_level(logging.INFO, logger="unit_commitment"):
        run_solve("priority_list", "small", 1, "day", 60, None)

    messages = [record.getMessage() for record in caplog.records]
    assert any("Job started" in m and "priority_list" in m and "small" in m for m in messages)
    assert any("Job finished" in m and "feasible=True" in m for m in messages)


def test_run_solve_logs_traceback_and_reraises_on_error(caplog):
    with caplog.at_level(logging.INFO, logger="unit_commitment"):
        with pytest.raises(ValueError):
            run_solve("magic", "small", 1, "day", 60, None)

    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert errors, "a failing job must produce an ERROR log entry"
    assert errors[0].exc_info is not None, "the log entry must contain the traceback"
