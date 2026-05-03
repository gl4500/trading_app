"""
FinBERT-based news headline sentiment scorer.

Replaces the keyword-counting `_score_headlines` for the CNN's `yahoo_news`
input channel (see Task #21). Uses ProsusAI/finbert (Apache 2.0, ~440 MB),
loaded lazily on first call and cached for the lifetime of the process.

Per-article score = P(positive) − P(negative)  (range: [−1, +1]).
Per-symbol score  = mean(per-article scores).

Returns None whenever the model is unavailable (transformers not installed,
weight download failed, inference threw) so callers can fall back to the
legacy keyword scorer without an exception bubbling up.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from transformers import pipeline as _hf_pipeline   # type: ignore
    HAS_TRANSFORMERS = True
except ImportError:
    _hf_pipeline = None   # type: ignore
    HAS_TRANSFORMERS = False
    logger.warning(
        "finbert_scorer: transformers not installed — falling back to keyword scorer"
    )

# Apache 2.0; free for commercial use. The model card lives at
# https://huggingface.co/ProsusAI/finbert. Pinned by name so that switching
# to a different finbert variant (e.g. yiyanghkust/finbert-tone) is a
# deliberate change reviewed in a follow-up commit.
_MODEL_NAME = "ProsusAI/finbert"

# FinBERT positional embedding limit is 512 tokens. We cap the per-article
# input at ~512 tokens worth of characters so the tokenizer doesn't have to
# truncate inside the call (which would still work — the pipeline passes
# truncation=True — but pre-trimming keeps payloads small for batching).
_MAX_INPUT_CHARS = 1500

# Lazy singleton — None means "not loaded yet OR last load attempt failed".
# Failed loads do NOT cache None (we re-attempt next call) so a transient
# download error doesn't permanently disable scoring for the process.
_pipeline: Any = None


def _get_pipeline() -> Any:
    """Return the cached HF text-classification pipeline, loading it on the
    first call. Returns None when transformers is missing or the model
    failed to load."""
    global _pipeline
    if not HAS_TRANSFORMERS or _hf_pipeline is None:
        return None
    if _pipeline is not None:
        return _pipeline
    try:
        # top_k=None returns scores for every class (positive, negative, neutral)
        # rather than only the argmax — we need all three to compute pos − neg.
        # device=-1 forces CPU; the GPU is reserved for Ollama (see CLAUDE.md
        # GPU constraint) and FinBERT-base is fast enough on CPU for ~5 headlines.
        _pipeline = _hf_pipeline(
            "text-classification",
            model=_MODEL_NAME,
            top_k=None,
            device=-1,
        )
        logger.info(f"finbert_scorer: loaded {_MODEL_NAME} on CPU")
    except Exception as exc:
        logger.warning(f"finbert_scorer: failed to load {_MODEL_NAME}: {exc}")
        return None
    return _pipeline


def _article_text(article: Dict[str, Any]) -> str:
    """Concatenate headline + summary into one string suitable for FinBERT.
    Skips the summary if it duplicates the headline (yfinance occasionally
    repeats the title in the summary field)."""
    headline = (article.get("headline") or "").strip()
    summary  = (article.get("summary")  or "").strip()
    if summary and summary != headline:
        text = f"{headline}. {summary}"
    else:
        text = headline
    return text[:_MAX_INPUT_CHARS]


def _aggregate_per_article(label_scores: List[Dict[str, Any]]) -> float:
    """Reduce one article's per-class scores to a single value in [−1, +1].
    Score = P(positive) − P(negative); P(neutral) is intentionally ignored
    (it's the implicit residual)."""
    pos = 0.0
    neg = 0.0
    for item in label_scores:
        label = str(item.get("label", "")).lower()
        score = float(item.get("score", 0.0))
        if label == "positive":
            pos = score
        elif label == "negative":
            neg = score
    return pos - neg


def score_headlines(articles: List[Dict[str, Any]]) -> Optional[float]:
    """Score a list of news articles in [−1, +1] using FinBERT, or return
    None when scoring is unavailable / no usable headlines were supplied.

    Parameters
    ----------
    articles : list of {"headline": str, "summary": str (optional)}

    Returns
    -------
    float in [−1, +1], or None.
    """
    if not articles:
        return None
    pipe = _get_pipeline()
    if pipe is None:
        return None

    texts = [_article_text(a) for a in articles if (a.get("headline") or "").strip()]
    if not texts:
        return None

    try:
        # truncation=True is a belt-and-braces guard against any text that
        # slipped past _MAX_INPUT_CHARS (e.g. multibyte chars expanding under
        # the BPE tokenizer).
        results = pipe(texts, truncation=True)
    except Exception as exc:
        logger.warning(f"finbert_scorer: inference failed: {exc}")
        return None

    if not results:
        return None

    per_article_scores = [_aggregate_per_article(r) for r in results]
    return float(sum(per_article_scores) / len(per_article_scores))
