"""Run pytest with the repository's requirement for an executed test case."""

import sys

import pytest


class ExecutedTests:
    def __init__(self):
        self.executed = False

    def pytest_runtest_logreport(self, report):
        # Expected failures count only when their test body actually ran.
        # Plain skips, including skips in the body, do not satisfy the gate.
        if report.when == "call" and (
            not report.skipped or hasattr(report, "wasxfail")
        ):
            self.executed = True

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session):
        # Let normal failure codes and other plugins (notably the repository
        # tripwire) take precedence before rejecting a wholly skipped run.
        yield
        inspection = any(
            session.config.getoption(option, default=False)
            for option in (
                "collectonly",
                "setupplan",
                "setuponly",
                "showfixtures",
                "show_fixtures_per_test",
            )
        )
        if (
            session.exitstatus == pytest.ExitCode.OK
            and not inspection
            and not self.executed
        ):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            print("test: no test cases executed; wholly skipped suite", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[ExecutedTests()]))
