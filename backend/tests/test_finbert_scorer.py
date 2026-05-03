"""
Unit tests for data/finbert_scorer.py
Covers: score_headlines(), pipeline lazy loading, graceful degrade when
transformers is missing or the model fails to load. Real FinBERT weights are
NEVER loaded — tests mock the pipeline.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data import finbert_scorer as fs


def _mock_pipe(scores_per_article):
    """Build a callable that mimics the HF text-classification pipeline output
    when invoked with `top_k=None`. `scores_per_article` is a list of
    (P(positive), P(negative), P(neutral)) tuples — one per input text."""
    def _pipe(texts, **kwargs):
        out = []
        for i, _text in enumerate(texts):
            pos, neg, neu = scores_per_article[i]
            out.append([
                {"label": "positive", "score": float(pos)},
                {"label": "negative", "score": float(neg)},
                {"label": "neutral",  "score": float(neu)},
            ])
        return out
    return _pipe


class TestScoreHeadlines(unittest.TestCase):

    def setUp(self):
        # Reset cached pipeline between tests so patch.object on _get_pipeline
        # doesn't get bypassed by a stale singleton from a previous test.
        fs._pipeline = None

    def test_returns_none_for_empty_articles(self):
        self.assertIsNone(fs.score_headlines([]))

    def test_returns_none_when_pipeline_unavailable(self):
        with patch.object(fs, "_get_pipeline", return_value=None):
            result = fs.score_headlines([{"headline": "Stock surges on guidance"}])
        self.assertIsNone(result)

    def test_returns_none_for_articles_with_no_headlines(self):
        # Article has only summary; headline is empty/missing → nothing to score
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([])):
            result = fs.score_headlines([{"summary": "summary only, no headline"}])
        self.assertIsNone(result)

    def test_positive_headline_returns_positive_score(self):
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([(0.85, 0.05, 0.10)])):
            result = fs.score_headlines([{"headline": "AAPL beats earnings"}])
        # P(pos) − P(neg) = 0.85 − 0.05 = 0.80
        self.assertAlmostEqual(result, 0.80, places=5)

    def test_negative_headline_returns_negative_score(self):
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([(0.05, 0.85, 0.10)])):
            result = fs.score_headlines([{"headline": "AAPL plunges on guidance cut"}])
        self.assertAlmostEqual(result, -0.80, places=5)

    def test_neutral_headline_near_zero(self):
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([(0.10, 0.10, 0.80)])):
            result = fs.score_headlines([{"headline": "AAPL announces conference call"}])
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_aggregates_mean_across_multiple_articles(self):
        pipe = _mock_pipe([
            (0.80, 0.10, 0.10),  # +0.70
            (0.10, 0.80, 0.10),  # −0.70
            (0.50, 0.30, 0.20),  # +0.20
        ])
        articles = [{"headline": f"h{i}"} for i in range(3)]
        with patch.object(fs, "_get_pipeline", return_value=pipe):
            result = fs.score_headlines(articles)
        # mean(0.70, -0.70, 0.20) = 0.0666...
        self.assertAlmostEqual(result, (0.70 - 0.70 + 0.20) / 3, places=4)

    def test_concatenates_headline_and_summary(self):
        captured = []
        def _pipe(texts, **kwargs):
            captured.extend(texts)
            return [[
                {"label": "positive", "score": 0.5},
                {"label": "negative", "score": 0.3},
                {"label": "neutral",  "score": 0.2},
            ]] * len(texts)
        with patch.object(fs, "_get_pipeline", return_value=_pipe):
            fs.score_headlines([{"headline": "AAPL up", "summary": "after Q3 beat"}])
        self.assertEqual(len(captured), 1)
        self.assertIn("AAPL up", captured[0])
        self.assertIn("Q3 beat", captured[0])

    def test_does_not_duplicate_summary_when_equal_to_headline(self):
        captured = []
        def _pipe(texts, **kwargs):
            captured.extend(texts)
            return [[
                {"label": "positive", "score": 0.4},
                {"label": "negative", "score": 0.3},
                {"label": "neutral",  "score": 0.3},
            ]] * len(texts)
        with patch.object(fs, "_get_pipeline", return_value=_pipe):
            fs.score_headlines([{"headline": "AAPL up", "summary": "AAPL up"}])
        # Summary identical → don't include it twice
        self.assertEqual(captured[0].count("AAPL up"), 1)

    def test_truncates_long_text_for_finbert_max_length(self):
        long_summary = "lorem ipsum " * 1000
        captured = []
        def _pipe(texts, **kwargs):
            captured.extend(texts)
            return [[
                {"label": "positive", "score": 0.5},
                {"label": "negative", "score": 0.3},
                {"label": "neutral",  "score": 0.2},
            ]] * len(texts)
        with patch.object(fs, "_get_pipeline", return_value=_pipe):
            fs.score_headlines([{"headline": "AAPL", "summary": long_summary}])
        # FinBERT positional limit is 512 tokens; we cap chars well under that.
        self.assertLessEqual(len(captured[0]), fs._MAX_INPUT_CHARS)

    def test_inference_exception_returns_none(self):
        def _bad_pipe(texts, **kwargs):
            raise RuntimeError("CUDA OOM")
        with patch.object(fs, "_get_pipeline", return_value=_bad_pipe):
            result = fs.score_headlines([{"headline": "AAPL"}])
        self.assertIsNone(result)

    def test_skips_articles_with_blank_headlines(self):
        # Two articles: first has headline, second has only whitespace
        pipe = _mock_pipe([(0.6, 0.2, 0.2)])
        with patch.object(fs, "_get_pipeline", return_value=pipe):
            result = fs.score_headlines([
                {"headline": "AAPL up"},
                {"headline": "   "},
            ])
        # Only the first article contributes — score = 0.6 − 0.2 = 0.4
        self.assertAlmostEqual(result, 0.4, places=5)

    def test_score_within_unit_interval(self):
        # Even at the extremes (P(pos)=1, P(neg)=0), the per-article score is
        # P(pos) − P(neg), which is bounded in [−1, +1] for any valid softmax.
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([(1.0, 0.0, 0.0)])):
            self.assertLessEqual(fs.score_headlines([{"headline": "x"}]), 1.0)
        with patch.object(fs, "_get_pipeline", return_value=_mock_pipe([(0.0, 1.0, 0.0)])):
            self.assertGreaterEqual(fs.score_headlines([{"headline": "x"}]), -1.0)


class TestPipelineLazyLoad(unittest.TestCase):

    def setUp(self):
        fs._pipeline = None

    def test_pipeline_singleton_loaded_once(self):
        fake_pipe = MagicMock(name="hf_pipeline_instance")
        with patch.object(fs, "_hf_pipeline", return_value=fake_pipe) as ctor:
            p1 = fs._get_pipeline()
            p2 = fs._get_pipeline()
        self.assertIs(p1, p2)
        ctor.assert_called_once()

    def test_pipeline_load_failure_returns_none(self):
        with patch.object(fs, "_hf_pipeline", side_effect=OSError("model missing")):
            result = fs._get_pipeline()
        self.assertIsNone(result)

    def test_pipeline_load_failure_does_not_cache_none(self):
        # If first call fails, subsequent calls should retry (don't cache the
        # failure) — otherwise a transient HF download error would permanently
        # disable FinBERT for the process lifetime.
        with patch.object(fs, "_hf_pipeline", side_effect=OSError("network blip")):
            self.assertIsNone(fs._get_pipeline())
        fake_pipe = MagicMock()
        with patch.object(fs, "_hf_pipeline", return_value=fake_pipe):
            self.assertIs(fs._get_pipeline(), fake_pipe)


class TestModuleConstants(unittest.TestCase):

    def test_model_name_is_prosus_finbert(self):
        # Lock in the specific model — Apache 2.0, free, ~440 MB.
        # Switching to a different finbert variant should be a deliberate change.
        self.assertEqual(fs._MODEL_NAME, "ProsusAI/finbert")

    def test_max_input_chars_under_finbert_token_limit(self):
        # FinBERT max position embeddings = 512 tokens. ~3 chars/token is a
        # safe lower bound, so 512 * 3 = 1536. Anything ≤ that is safe.
        self.assertLessEqual(fs._MAX_INPUT_CHARS, 1536)


if __name__ == "__main__":
    unittest.main()
