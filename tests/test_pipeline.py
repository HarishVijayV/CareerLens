"""
Tests for pipeline logic that doesn't need Spark or a database running — the data
generator's guarantees and the ingestion relevance filter.

The Spark jobs themselves are verified by actually running them (pipeline/run_pipeline.py)
plus dbt's 17 data-quality tests against the loaded warehouse; unit-testing Spark in CI
would mean booting a JVM for little added signal.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline" / "ingestion"))

from generate_synthetic_data import generate  # noqa: E402
from job_apis import _matches_terms  # noqa: E402


class TestSyntheticGenerator:
    def test_generates_requested_row_count(self, tmp_path):
        out = tmp_path / "postings.jsonl"
        generate(1000, out, seed=42)
        assert sum(1 for _ in out.open()) == 1000

    def test_is_deterministic_with_a_seed(self, tmp_path):
        """Reproducibility matters: without it, "the numbers changed" could mean a real
        regression or just new random data, and you can't tell which."""
        a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
        generate(200, a, seed=7)
        generate(200, b, seed=7)
        assert a.read_text() == b.read_text()

    def test_injects_duplicates_for_the_etl_to_remove(self, tmp_path):
        """The generator deliberately emits duplicate postings so the Spark dedup step has
        real work to do. If this stopped happening, the dedup logic would be untested by
        the end-to-end run."""
        out = tmp_path / "postings.jsonl"
        generate(5000, out, seed=42)
        ids = [json.loads(line)["posting_id"] for line in out.open()]
        assert len(ids) > len(set(ids))

    def test_injects_messy_salaries(self, tmp_path):
        """Some salaries are strings like "$120,000/yr" and some are null — that's what
        makes the ETL's cleaning step meaningful rather than a pass-through."""
        out = tmp_path / "postings.jsonl"
        generate(5000, out, seed=42)
        salaries = [json.loads(line)["salary"] for line in out.open()]
        assert any(isinstance(s, str) for s in salaries)
        assert any(s is None for s in salaries)
        assert any(isinstance(s, int) for s in salaries)

    def test_seasonality_is_present(self, tmp_path):
        """December is weighted low on purpose. The analytics page claims a hiring dip —
        this asserts the claim is actually true of the data."""
        out = tmp_path / "postings.jsonl"
        generate(20000, out, seed=42)
        months = [json.loads(line)["posted_month"] for line in out.open()]
        december = months.count(12)
        january = months.count(1)
        assert december < january


class TestRelevanceFilter:
    """Regression tests for a real bug: Remotive's `search` param doesn't filter, so
    "Data Engineer" returned "Sales Jedi" and "Freelance Copywriter"."""

    def test_exact_title_match(self):
        assert _matches_terms("Senior Data Engineer", [], ["Data Engineer"])

    def test_words_in_any_order(self):
        assert _matches_terms("Engineer, Data Platform", [], ["Data Engineer"])

    def test_rejects_unrelated_roles(self):
        assert not _matches_terms("Sales Jedi", [], ["Data Engineer"])
        assert not _matches_terms("Freelance Copywriter", [], ["Data Engineer"])

    def test_noisy_tags_do_not_rescue_an_unrelated_title(self):
        """The original bug: matching against tags let a copywriting role tagged "data"
        through. Only the title decides."""
        assert not _matches_terms("Freelance Copywriter", ["data", "python"], ["Data Engineer"])

    def test_no_terms_means_no_filtering(self):
        assert _matches_terms("Anything At All", [], [])

    def test_case_insensitive(self):
        assert _matches_terms("SENIOR DATA ENGINEER", [], ["data engineer"])
