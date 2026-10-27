"""Tests for how evals/run.py acts on a failed-row verdict.

Only the wiring lives here, because evals.run imports assay at module level and
so skips wherever the eval harness is absent (CI installs requirements.txt only).
The verdict itself comes from ``evals.generate.failed_rows``, tested in
tests/test_generate.py, which runs everywhere.
"""

import json

import pytest

pytest.importorskip("assay")

import evals.run as run  # noqa: E402


def _outputs(path, rows):
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": case_id,
                    "input": {"question": case_id, "max_iterations": 1},
                    "expected": {},
                    "metadata": {},
                    "output": {"text": text,
                               "data": {"text": text, "sources": [],
                                        **({"error": error} if error else {})}},
                }
            )
            for case_id, text, error in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_scoring_a_file_with_failures_is_refused(monkeypatch, tmp_path, capsys):
    path = _outputs(tmp_path / "out.jsonl",
                    [("ok", "# Report", None), ("bad", "", "RuntimeError: boom")])
    monkeypatch.setattr("sys.argv", ["run", "--from-outputs", str(path)])

    with pytest.raises(SystemExit) as exc:
        run.main()

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "1 case(s)" in err
    assert "- bad: RuntimeError: boom" in err
    assert "--resume" in err, "should point at the retry path"
    assert "--allow-failed" in err, "should name the override"


def test_allow_failed_warns_instead_of_refusing(monkeypatch, tmp_path, capsys):
    path = _outputs(tmp_path / "out.jsonl",
                    [("ok", "# Report", None), ("bad", "", "RuntimeError: boom")])
    monkeypatch.setattr("sys.argv",
                        ["run", "--from-outputs", str(path), "--allow-failed",
                         "--skip-judge", "--concurrency", "1"])

    # Getting past the guard is the assertion; what the run does afterwards
    # (writing a report dir, etc.) is not this test's business.
    try:
        run.main()
    except BaseException:
        pass

    err = capsys.readouterr().err
    assert "--allow-failed was passed" in err
    assert "bad" in err
