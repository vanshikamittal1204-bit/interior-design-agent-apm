"""Gemini-powered semantic scope classifier for the interior design agent."""

import json
import logging
import os
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import google.generativeai as genai
    import google.api_core.exceptions as _gapi_exc
    # Extract specific exception classes so except clauses resolve at import time.
    _DeadlineExceeded = _gapi_exc.DeadlineExceeded
    _ResourceExhausted = _gapi_exc.ResourceExhausted
    _InvalidArgument = _gapi_exc.InvalidArgument
    _PermissionDenied = _gapi_exc.PermissionDenied
    _Unauthenticated = _gapi_exc.Unauthenticated
except ImportError:
    genai = None  # type: ignore[assignment]
    # Sentinel stubs — never raised in practice, but required so except clauses
    # below remain valid Python even when google-generativeai is not installed.
    class _DeadlineExceeded(Exception): pass  # type: ignore[misc]
    class _ResourceExhausted(Exception): pass  # type: ignore[misc]
    class _InvalidArgument(Exception): pass  # type: ignore[misc]
    class _PermissionDenied(Exception): pass  # type: ignore[misc]
    class _Unauthenticated(Exception): pass  # type: ignore[misc]

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD: float = 0.80
_MODEL_NAME: str = "gemini-2.5-flash"

_PROMPT_TEMPLATE: str = """\
You are a scope classifier for an interior design planning agent.

Your task is to determine whether a user's interior design request contains
any work that is outside the scope of furniture selection and arrangement.

OUT-OF-SCOPE work includes:
- Structural modifications: removing walls, adding partitions, load-bearing changes
- Electrical work: wiring, adding outlets, switchboards, circuit upgrades
- Plumbing work: pipes, drains, taps, faucets, toilets, drainage relocation
- HVAC work: ductwork, ventilation installation, air conditioning systems
- Renovation or demolition: gutting rooms, tearing out fittings
- Construction activities: building new structures, raising or lowering ceilings,
  laying floors, build a mezzanine, construct a partition, extend the room,
  build a utility area

IN-SCOPE work includes:
- Furniture selection and placement (sofas, tables, chairs, beds, wardrobes)
- Decorative elements (rugs, cushions, wall art, plants, lamps as furniture items)
- Style and aesthetic guidance
- Lighting fixtures selected as furniture items (not electrical wiring work)
- Storage solutions using furniture

Room type: {room_type}
User request: {combined_text}

Respond with ONLY valid JSON matching this schema exactly. No text outside the JSON.
{{
  "is_out_of_scope": <boolean>,
  "category": <one of "structural"|"electrical"|"plumbing"|"hvac"|"renovation"|"construction"|"none">,
  "reason": <string explaining the classification>,
  "confidence": <float between 0.0 and 1.0>
}}\
"""


class ClassificationResult(BaseModel):
    """Validated result from Gemini scope classification."""

    is_out_of_scope: bool
    category: Literal[
        "structural", "electrical", "plumbing",
        "hvac", "renovation", "construction", "none",
    ]
    reason: str
    confidence: float


class GeminiScopeClassifier:
    """Semantic out-of-scope classifier backed by Gemini.

    Returns None on any failure so the caller can fall back to its own
    default behaviour without surfacing Gemini errors to the user.
    """

    def __init__(self) -> None:
        self._api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
        # Check `genai is not None` at construction time so that test patches
        # that replace the module-level `genai` name are correctly detected.
        self._available: bool = (genai is not None) and bool(self._api_key)
        if genai is None:
            logger.warning("google-generativeai not installed; Gemini scope classifier disabled")
        elif not self._api_key:
            logger.warning("GEMINI_API_KEY not set; Gemini scope classifier disabled")

    def classify(self, room_type: str, combined_text: str) -> Optional[ClassificationResult]:
        """Return a ClassificationResult, or None on any failure.

        None means "no opinion" — the caller must treat it as a non-rejection.
        """
        if not self._available:
            return None

        try:
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel(
                model_name=_MODEL_NAME,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            prompt = _PROMPT_TEMPLATE.format(
                room_type=room_type,
                combined_text=combined_text,
            )
            response = model.generate_content(
                prompt,
                request_options={"timeout": 5},
            )
            data = json.loads(response.text)
            return ClassificationResult.model_validate(data)

        except _DeadlineExceeded:
            logger.warning("Gemini scope classifier timed out; using phrase-match fallback")
        except _ResourceExhausted:
            logger.warning("Gemini quota exceeded; using phrase-match fallback")
        except (_InvalidArgument, _PermissionDenied, _Unauthenticated):
            logger.warning("Gemini API key error; using phrase-match fallback")
        except json.JSONDecodeError:
            logger.warning("Gemini returned malformed JSON; using phrase-match fallback")
        except ValidationError as exc:
            logger.warning(
                "Gemini JSON failed schema validation (%s); using phrase-match fallback", exc
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Gemini error (%s); using phrase-match fallback", type(exc).__name__
            )

        return None
