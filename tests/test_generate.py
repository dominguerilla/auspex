"""Tests for output generation (evals/generate.py).

Fully offline: the adapter is replaced with a stub, so no LLM or network is
touched. The point under test is failure accounting — a case that produces no
report must be reported and must fail the process, because scoring it as-is
would grade an infra failure as a wrong answer and bias the A/B arm.
"""

import json

import pytest

import evals.generate as generate


def _write_dataset(path, ids):
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": case_id,
                    "input": {"question": case_id, "max_iterations": 1},
                    "expected": {},
                    "metadata": {},
                }
            )
            for case_id in ids
        )
        + "\n",
        encoding="utf-8",
    )


def _report(text):
    return {
        "text": text,
        "data": {"text": text, "sources": [], "critique": None, "iterations_used": 1},
    }


def _run(monkeypatch, tmp_path, ids, agent, extra=()):
    """Stage a run. Defaults to one attempt and no backoff so tests don't sleep."""
    dataset = tmp_path / "cases.jsonl"
    output = tmp_path / "out.jsonl"
    _write_dataset(dataset, ids)
    monkeypatch.setattr(generate, "agent", agent)
    monkeypatch.setattr(
        "sys.argv",
        ["generate", "--dataset", str(dataset), "--output", str(output),
         "--skip-connectivity-check", "--attempts", "1", "--retry-backoff", "0",
         *extra],
    )
    return output


def _rows(output):
    return [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_all_cases_succeed_exits_cleanly(monkeypatch, tmp_path):
    output = _run(monkeypatch, tmp_path, ["a", "b"], lambda _: _report("# Report"))

    generate.main()

    rows = _rows(output)
    assert [r["id"] for r in rows] == ["a", "b"]
    assert all(r["output"]["data"].get("error") is None for r in rows)


def test_raising_case_is_recorded_and_fails_the_run(monkeypatch, tmp_path):
    def agent(input_):
        if input_["question"] == "bad":
            raise RuntimeError("ollama connection reset")
        return _report("# Report")

    output = _run(monkeypatch, tmp_path, ["good", "bad"], agent)

    with pytest.raises(SystemExit) as exc:
        generate.main()
    assert exc.value.code == 1

    rows = {r["id"]: r for r in _rows(output)}
    # The row is still written, so the file stays aligned with the dataset.
    assert len(rows) == 2
    assert rows["good"]["output"]["data"].get("error") is None
    assert "ollama connection reset" in rows["bad"]["output"]["data"]["error"]


def test_empty_report_without_exception_counts_as_a_failure(monkeypatch, tmp_path):
    # The graph can finish without raising and still yield no report; that must
    # be marked the same way as a thrown exception, not scored as an answer.
    output = _run(monkeypatch, tmp_path, ["blank"], lambda _: _report("   "))

    with pytest.raises(SystemExit) as exc:
        generate.main()
    assert exc.value.code == 1

    (row,) = _rows(output)
    assert row["output"]["data"]["error"].startswith("empty report")


def test_failure_summary_names_every_failed_case(monkeypatch, tmp_path, capsys):
    def agent(input_):
        raise RuntimeError("boom")

    _run(monkeypatch, tmp_path, ["x", "y"], agent)

    with pytest.raises(SystemExit):
        generate.main()

    err = capsys.readouterr().err
    assert "2/2 cases produced no report" in err
    assert "- x: RuntimeError: boom" in err
    assert "- y: RuntimeError: boom" in err


# --- retries (--attempts) ---------------------------------------------------


def test_transient_failure_is_retried_and_succeeds(monkeypatch, tmp_path):
    calls = []

    def flaky(input_):
        calls.append(input_["question"])
        if len(calls) == 1:
            raise RuntimeError("ollama connection reset")
        return _report("# Report")

    output = _run(monkeypatch, tmp_path, ["a"], flaky,
                  extra=["--attempts", "3", "--retry-backoff", "0"])

    generate.main()  # must not raise SystemExit

    assert len(calls) == 2
    (row,) = _rows(output)
    assert row["output"]["data"].get("error") is None


def test_empty_report_is_retried_too(monkeypatch, tmp_path):
    calls = []

    def flaky(input_):
        calls.append(input_["question"])
        return _report("" if len(calls) == 1 else "# Report")

    output = _run(monkeypatch, tmp_path, ["a"], flaky,
                  extra=["--attempts", "2", "--retry-backoff", "0"])

    generate.main()

    assert len(calls) == 2
    (row,) = _rows(output)
    assert row["output"]["data"].get("error") is None


def test_retries_are_bounded_and_then_recorded(monkeypatch, tmp_path):
    calls = []

    def always_fails(input_):
        calls.append(1)
        raise RuntimeError("boom")

    output = _run(monkeypatch, tmp_path, ["a"], always_fails,
                  extra=["--attempts", "3", "--retry-backoff", "0"])

    with pytest.raises(SystemExit) as exc:
        generate.main()
    assert exc.value.code == 1

    assert len(calls) == 3
    (row,) = _rows(output)
    assert row["output"]["data"]["error"] == "RuntimeError: boom"


def test_attempts_below_one_is_rejected(monkeypatch, tmp_path):
    _run(monkeypatch, tmp_path, ["a"], lambda _: _report("# Report"),
         extra=["--attempts", "0"])

    with pytest.raises(SystemExit) as exc:
        generate.main()
    assert exc.value.code == 1


# --- resume ----------------------------------------------------------------


def test_resume_reuses_successes_and_reruns_failures(monkeypatch, tmp_path):
    # First pass: "a" succeeds, "b" fails.
    def first_pass(input_):
        if input_["question"] == "b":
            raise RuntimeError("boom")
        return _report("# First report")

    output = _run(monkeypatch, tmp_path, ["a", "b"], first_pass)
    with pytest.raises(SystemExit):
        generate.main()

    # Second pass with --resume: only "b" should be re-run.
    seen = []

    def second_pass(input_):
        seen.append(input_["question"])
        return _report("# Second report")

    _run(monkeypatch, tmp_path, ["a", "b"], second_pass, extra=["--resume"])
    generate.main()

    assert seen == ["b"], "only the failed case should re-run"
    rows = {r["id"]: r for r in _rows(output)}
    assert len(rows) == 2
    # The reused row keeps its original text; the retried one is fresh.
    assert rows["a"]["output"]["text"] == "# First report"
    assert rows["b"]["output"]["text"] == "# Second report"
    assert all(r["output"]["data"].get("error") is None for r in rows.values())


def test_resume_tolerates_a_truncated_last_line(monkeypatch, tmp_path):
    # A run killed mid-write leaves a partial JSON line; it must not crash resume.
    output = _run(monkeypatch, tmp_path, ["a", "b"], lambda _: _report("# R"))
    output.write_text(
        json.dumps({"id": "a", "input": {"question": "a", "max_iterations": 1},
                    "output": {"text": "# Kept", "data": {}}}) + "\n"
        + '{"id": "b", "inp',
        encoding="utf-8",
    )

    seen = []

    def agent(input_):
        seen.append(input_["question"])
        return _report("# Fresh")

    _run(monkeypatch, tmp_path, ["a", "b"], agent, extra=["--resume"])
    generate.main()

    assert seen == ["b"]
    rows = {r["id"]: r for r in _rows(output)}
    assert rows["a"]["output"]["text"] == "# Kept"
    assert rows["b"]["output"]["text"] == "# Fresh"


# --- failed_rows: the verdict evals.run acts on -----------------------------


def _outputs_file(path, rows):
    path.write_text(
        "\n".join(
            json.dumps({"id": case_id,
                        "output": {"text": text,
                                   "data": {"text": text,
                                            **({"error": error} if error else {})}}})
            for case_id, text, error in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_failed_rows_empty_for_a_clean_file(tmp_path):
    path = _outputs_file(tmp_path / "out.jsonl",
                         [("a", "# Report", None), ("b", "# Report", None)])

    assert generate.failed_rows(path) == []


def test_failed_rows_detects_both_failure_shapes(tmp_path):
    path = _outputs_file(
        tmp_path / "out.jsonl",
        [
            ("ok", "# Report", None),
            ("raised", "", "RuntimeError: ollama connection reset"),
            ("blank", "", "empty report (graph completed without raising)"),
        ],
    )

    failed = generate.failed_rows(path)

    assert [case_id for case_id, _ in failed] == ["raised", "blank"]
    assert "ollama connection reset" in dict(failed)["raised"]


def test_failed_rows_ignores_blank_and_truncated_lines(tmp_path):
    path = _outputs_file(tmp_path / "out.jsonl", [("a", "# Report", None)])
    path.write_text(path.read_text(encoding="utf-8") + '\n\n{"id": "b", "inp',
                    encoding="utf-8")

    assert generate.failed_rows(path) == []
