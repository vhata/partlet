from partlet.publish import ProjectResult
from partlet.summary import REASON_LIMIT, summary_markdown, write_summary


def test_table_rows_and_tools():
    text = summary_markdown(
        "Partlet publish",
        [
            ProjectResult("foo", "published", "a" * 40, "first publication"),
            ProjectResult("bar", "skipped", None, "not approved"),
        ],
        {"partlet": "0.1.0", "gitleaks": "8.30.1"},
    )
    assert "| foo | published | `aaaaaaaaaaaa` | first publication |" in text
    assert "| bar | skipped |  | not approved |" in text
    assert "Tools: partlet 0.1.0, gitleaks 8.30.1" in text


def test_reasons_cannot_break_the_table_or_inject_html():
    reason = "line one\nline | two <script>x</script> " + "y" * 400
    text = summary_markdown("T", [ProjectResult("foo", "failed", None, reason)], {})
    (row,) = [line for line in text.splitlines() if line.startswith("| foo")]
    assert "line one line \\| two &lt;script&gt;" in row
    assert "<script>" not in text
    assert row.count(" | ") == 3
    assert len(row) < REASON_LIMIT + 100


def test_write_summary_appends(tmp_path):
    path = tmp_path / "summary.md"
    write_summary(path, "one")
    write_summary(path, "two")
    write_summary(None, "ignored")
    assert path.read_text() == "one\ntwo\n"


def test_run_failure_is_escaped():
    text = summary_markdown("T", [], {}, error="locked | by <b>x</b>\nsince then")
    assert "Failed: locked \\| by &lt;b&gt;x&lt;/b&gt; since then" in text
