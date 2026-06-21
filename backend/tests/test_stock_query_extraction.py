"""Regression tests for the stock-search query refinement.

Cinematic prompts work great for Flux/Kling/Veo/Pika but tank Pexels'
keyword-tag search relevance. We extract noun-only keywords for stock
libraries while keeping the full cinematic prompt for AI engines.
"""
import sys
sys.path.insert(0, "/app/backend")

from server import _extract_stock_query, _score_pexels_hit


class TestExtractStockQuery:
    def test_strips_shot_type_words(self):
        out = _extract_stock_query(
            "Wide overhead shot of hands chopping fresh vegetables on a wooden board"
        )
        assert "wide" not in out
        assert "overhead" not in out
        assert "shot" not in out
        assert "hands" in out
        assert "vegetables" in out

    def test_strips_camera_motion(self):
        out = _extract_stock_query(
            "Tracking pan across rolling green hills with slow forward drift"
        )
        assert "tracking" not in out
        assert "pan" not in out
        assert "drift" not in out
        assert "hills" in out

    def test_strips_lighting_modifiers(self):
        out = _extract_stock_query(
            "Close-up of espresso pour, golden warm soft daylight, shallow depth of field"
        )
        # Lighting words gone
        assert "golden" not in out
        assert "warm" not in out
        assert "soft" not in out
        assert "shallow" not in out
        # Real subject preserved
        assert "espresso" in out
        assert "pour" in out

    def test_capped_at_six_words(self):
        out = _extract_stock_query(
            "businesswoman typing laptop coffee cup office desk window plant phone notebook pen"
        )
        assert len(out.split()) <= 6

    def test_empty_input(self):
        assert _extract_stock_query("") == ""
        assert _extract_stock_query(None) == ""

    def test_short_words_dropped(self):
        """Two-letter and shorter words are filler; drop them."""
        out = _extract_stock_query("Close-up of a chef at work in his kitchen")
        # "a", "of", "at", "in" all gone; "his" kept because >2 letters
        tokens = out.split()
        assert all(len(t) > 2 for t in tokens)

    def test_realistic_sample_1(self):
        out = _extract_stock_query(
            "Wide overhead shot of hands chopping fresh vegetables on a wooden board, "
            "soft kitchen daylight, slow camera drift right"
        )
        assert out == "hands chopping fresh vegetables wooden board"

    def test_realistic_sample_2(self):
        out = _extract_stock_query(
            "Medium handheld shot of a businesswoman typing on laptop in modern home "
            "office, natural daylight"
        )
        # Order may vary slightly; just confirm the high-signal nouns survive
        words = set(out.split())
        assert "businesswoman" in words
        assert "typing" in words
        assert "laptop" in words
        # Filler is gone
        assert "medium" not in words
        assert "handheld" not in words
        assert "shot" not in words


class TestScorePexelsHit:
    def test_scores_by_tag_overlap(self):
        video = {
            "url": "https://www.pexels.com/video/woman-typing-laptop-12345",
            "user": {"name": "Stock Studio"},
            "tags": ["woman", "typing", "laptop", "office", "computer"],
        }
        score = _score_pexels_hit(video, {"woman", "typing", "laptop"})
        assert score == 3

    def test_zero_score_no_overlap(self):
        video = {"url": "https://x", "user": {"name": "Y"}, "tags": ["sunset", "beach"]}
        score = _score_pexels_hit(video, {"laptop", "office"})
        assert score == 0

    def test_handles_missing_fields(self):
        video = {}  # no tags, no user
        score = _score_pexels_hit(video, {"anything"})
        assert score == 0
