"""Tests for the Gemini scope classifier and the hybrid OOS detection flow."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agents.scope_classifier import (
    CONFIDENCE_THRESHOLD,
    ClassificationResult,
    GeminiScopeClassifier,
)
from planner.planner import Planner, PlannerRequest
from utils.db import DatabaseConnection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(payload: dict) -> MagicMock:
    """Build a mock Gemini response whose .text is the JSON-serialised payload."""
    r = MagicMock()
    r.text = json.dumps(payload)
    return r


def _oos_payload(category: str = "structural", confidence: float = 0.95) -> dict:
    return {
        "is_out_of_scope": True,
        "category": category,
        "reason": f"Request involves {category} work outside interior design scope.",
        "confidence": confidence,
    }


def _in_scope_payload() -> dict:
    return {
        "is_out_of_scope": False,
        "category": "none",
        "reason": "Request is a valid interior design task.",
        "confidence": 0.97,
    }


def _make_request(notes: str, room_type: str = "Living Room") -> PlannerRequest:
    return PlannerRequest(
        room_type=room_type,
        style="Scandinavian",
        budget=200_000,
        room_width_cm=500,
        room_depth_cm=400,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    connection = DatabaseConnection()
    yield connection
    connection.close()


@pytest.fixture
def planner(db):
    return Planner(db=db)


# ---------------------------------------------------------------------------
# TestGeminiScopeClassifier — unit tests, Gemini API mocked throughout
# ---------------------------------------------------------------------------

class TestGeminiScopeClassifier:
    """Unit tests for GeminiScopeClassifier. No real Gemini API calls are made."""

    # -- OOS detection -------------------------------------------------------

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_structural(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("structural"))
        )
        result = GeminiScopeClassifier().classify("living room", "move a structural wall")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "structural"
        assert result.confidence == 0.95

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_electrical(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("electrical"))
        )
        result = GeminiScopeClassifier().classify("living room", "upgrade the electrical circuits")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "electrical"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_plumbing(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("plumbing"))
        )
        result = GeminiScopeClassifier().classify("living room", "relocate the drainage system")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "plumbing"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_hvac(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("hvac"))
        )
        result = GeminiScopeClassifier().classify("living room", "install some hvac ducting for the room")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "hvac"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_renovation(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("renovation"))
        )
        result = GeminiScopeClassifier().classify("living room", "gut and redo the interior")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "renovation"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_oos_construction(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_oos_payload("construction"))
        )
        result = GeminiScopeClassifier().classify("living room", "build a mezzanine level")
        assert result is not None
        assert result.is_out_of_scope is True
        assert result.category == "construction"

    # -- In-scope pass-through -----------------------------------------------

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_in_scope_cozy_living_room(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_in_scope_payload())
        )
        result = GeminiScopeClassifier().classify("living room", "create a cozy living room")
        assert result is not None
        assert result.is_out_of_scope is False
        assert result.category == "none"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_in_scope_reading_corner(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_in_scope_payload())
        )
        result = GeminiScopeClassifier().classify("living room", "add a reading corner")
        assert result is not None
        assert result.is_out_of_scope is False

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_classify_in_scope_decorative_wall_art(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(_in_scope_payload())
        )
        result = GeminiScopeClassifier().classify("living room", "add decorative wall art")
        assert result is not None
        assert result.is_out_of_scope is False

    # -- Safe failure modes --------------------------------------------------

    def test_returns_none_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_returns_none_on_timeout(self, mock_genai):
        # Use TimeoutError as a stand-in; caught by the broad `except Exception` fallback.
        mock_genai.GenerativeModel.return_value.generate_content.side_effect = (
            TimeoutError("simulated deadline exceeded")
        )
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_returns_none_on_quota_exceeded(self, mock_genai):
        # Use PermissionError as a stand-in; caught by the broad `except Exception` fallback.
        mock_genai.GenerativeModel.return_value.generate_content.side_effect = (
            PermissionError("simulated quota exceeded")
        )
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_returns_none_on_malformed_json(self, mock_genai):
        bad_response = MagicMock()
        bad_response.text = "this is not json at all"
        mock_genai.GenerativeModel.return_value.generate_content.return_value = bad_response
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_returns_none_on_pydantic_validation_failure(self, mock_genai):
        # confidence is a string instead of float — fails Pydantic validation
        bad_payload = {
            "is_out_of_scope": True,
            "category": "electrical",
            "reason": "some reason",
            "confidence": "not-a-float",
        }
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(bad_payload)
        )
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_returns_none_on_generic_api_error(self, mock_genai):
        mock_genai.GenerativeModel.return_value.generate_content.side_effect = (
            RuntimeError("unexpected internal error")
        )
        result = GeminiScopeClassifier().classify("living room", "some request text")
        assert result is None

    # -- Confidence threshold ------------------------------------------------

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_confidence_threshold_constant_is_0_80(self, mock_genai):
        assert CONFIDENCE_THRESHOLD == 0.80

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("agents.scope_classifier.genai")
    def test_low_confidence_result_is_returned_to_caller(self, mock_genai):
        # The classifier returns the result regardless of confidence;
        # the threshold check lives in _check_out_of_scope on the Planner side.
        low_confidence = _oos_payload("structural", confidence=0.50)
        mock_genai.GenerativeModel.return_value.generate_content.return_value = (
            _make_response(low_confidence)
        )
        result = GeminiScopeClassifier().classify("living room", "some structural work")
        assert result is not None
        assert result.confidence == 0.50


# ---------------------------------------------------------------------------
# TestHybridOOSFlow — integration tests verifying the 3-step order in
# _check_out_of_scope().  All tests use a real Planner with a real DB but
# mock planner._scope_classifier.classify to avoid Gemini API calls.
# ---------------------------------------------------------------------------

class TestHybridOOSFlow:
    """Verifies room-type check → phrase match → Gemini ordering."""

    # -- Phrase match must block Gemini call ---------------------------------

    @pytest.mark.parametrize("notes,label", [
        ("rewire the apartment",         "rewire triggers phrase match"),
        ("remove wall between rooms",    "remove wall triggers phrase match"),
        ("plumbing work for wet bar",    "plumbing work triggers phrase match"),
        ("install air conditioning",     "install air conditioning triggers phrase match"),
    ])
    def test_phrase_match_blocks_gemini_call(self, planner, notes, label):
        """Gemini must NOT be called when phrase matching already detected OOS."""
        mock_classify = MagicMock(return_value=None)
        planner._scope_classifier.classify = mock_classify

        result = planner.generate_plan(_make_request(notes))

        assert result.out_of_scope_reason is not None, (
            f"Expected OOS rejection for '{label}'"
        )
        mock_classify.assert_not_called()

    # -- Gemini rejects unseen paraphrases -----------------------------------

    @pytest.mark.parametrize("notes,category,label", [
        ("move a structural wall",         "structural",    "structural paraphrase"),
        ("upgrade the electrical circuits", "electrical",   "electrical paraphrase"),
        ("relocate the drainage system",    "plumbing",     "plumbing paraphrase"),
        ("gut and redo the interior",       "renovation",   "renovation paraphrase"),
        ("build a mezzanine level",         "construction", "construction paraphrase"),
    ])
    def test_gemini_rejects_unseen_paraphrase(self, planner, notes, category, label):
        """Phrase matching passes; Gemini classifies as OOS with high confidence."""
        oos_result = ClassificationResult(
            is_out_of_scope=True,
            category=category,
            reason=f"Gemini detected {category} work.",
            confidence=0.95,
        )
        planner._scope_classifier.classify = MagicMock(return_value=oos_result)

        result = planner.generate_plan(_make_request(notes))

        assert result.out_of_scope_reason is not None, (
            f"Expected Gemini OOS rejection for '{label}'"
        )
        assert result.selected_items == []
        planner._scope_classifier.classify.assert_called_once()

    # -- Confidence threshold gate -------------------------------------------

    def test_gemini_low_confidence_does_not_reject(self, planner):
        """A Gemini OOS result below the confidence threshold must NOT reject."""
        low_conf_result = ClassificationResult(
            is_out_of_scope=True,
            category="structural",
            reason="Maybe structural, not sure.",
            confidence=0.70,  # below CONFIDENCE_THRESHOLD (0.80)
        )
        planner._scope_classifier.classify = MagicMock(return_value=low_conf_result)

        result = planner.generate_plan(_make_request("I need help with my room layout"))

        assert result.out_of_scope_reason is None, (
            "Low-confidence Gemini result must not trigger rejection"
        )

    def test_gemini_exactly_at_threshold_rejects(self, planner):
        """A Gemini OOS result at exactly 0.80 confidence must reject."""
        threshold_result = ClassificationResult(
            is_out_of_scope=True,
            category="electrical",
            reason="Electrical work detected.",
            confidence=CONFIDENCE_THRESHOLD,  # exactly 0.80
        )
        planner._scope_classifier.classify = MagicMock(return_value=threshold_result)

        result = planner.generate_plan(_make_request("I want to change my circuit layout"))

        assert result.out_of_scope_reason is not None, (
            "Gemini result at exactly the threshold must reject"
        )

    # -- Gemini passes valid design requests ---------------------------------

    @pytest.mark.parametrize("notes,label", [
        ("create a cozy living room",          "cozy living room"),
        ("add a reading corner",               "reading corner"),
        ("Scandinavian bedroom with storage",  "Scandinavian storage"),
        ("improve lighting ambience",          "lighting ambience"),
        ("add decorative wall art",            "decorative wall art"),
    ])
    def test_gemini_passes_valid_design_request(self, planner, notes, label):
        """When Gemini returns in-scope, out_of_scope_reason must be None."""
        in_scope = ClassificationResult(
            is_out_of_scope=False,
            category="none",
            reason="Valid interior design request.",
            confidence=0.97,
        )
        planner._scope_classifier.classify = MagicMock(return_value=in_scope)

        result = planner.generate_plan(_make_request(notes))

        assert result.out_of_scope_reason is None, (
            f"Valid design note '{label}' was incorrectly rejected"
        )

    # -- Gemini failure must not block planning ------------------------------

    def test_gemini_failure_does_not_block_planning(self, planner):
        """When Gemini returns None (any failure), planning must continue."""
        planner._scope_classifier.classify = MagicMock(return_value=None)

        result = planner.generate_plan(_make_request("add a reading corner"))

        assert result.out_of_scope_reason is None

    def test_gemini_timeout_does_not_block_planning(self, planner):
        """When classify() raises internally and returns None, planning must continue."""
        # Simulate the classifier already having absorbed the exception and returning None
        planner._scope_classifier.classify = MagicMock(return_value=None)

        result = planner.generate_plan(
            _make_request("Scandinavian bedroom with storage", room_type="Living Room")
        )

        assert result.out_of_scope_reason is None

    # -- Room type check fires before phrase match and Gemini ----------------

    def test_room_type_check_blocks_before_phrase_and_gemini(self, planner):
        """Unsupported room type must be rejected immediately; Gemini is never called."""
        mock_classify = MagicMock(return_value=None)
        planner._scope_classifier.classify = mock_classify

        result = planner.generate_plan(
            PlannerRequest(
                room_type="garage",
                style="Scandinavian",
                budget=200_000,
                room_width_cm=500,
                room_depth_cm=400,
            )
        )

        assert result.out_of_scope_reason is not None
        mock_classify.assert_not_called()
