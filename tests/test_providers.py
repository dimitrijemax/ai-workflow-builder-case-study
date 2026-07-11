from pathlib import Path

from ai_workflow_builder.pipeline import load_ops_notes
from ai_workflow_builder.providers import DeterministicRuleProvider, InsightProvider
from ai_workflow_builder.schemas import OpsInsight, OpsNote

EXAMPLE_NOTES_PATH = Path(__file__).resolve().parents[1] / "examples" / "synthetic_ops_notes.json"

# Frozen characterization of the current deterministic provider for every bundled synthetic
# note. This locks category priority and keywords, negative-before-positive sentiment, the
# 0.48/0.58/0.82 confidence tiers, summary text, and action text. The two queued low-confidence
# cases (N-1004 at 0.58, N-1008 at 0.48) are captured in full below.
EXPECTED_INSIGHTS = [
    {
        "note_id": "N-1001",
        "category": "data_quality",
        "sentiment": "neutral",
        "summary": (
            "Note N-1001 is categorized as data_quality with neutral stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": ["Compare the source export, report surface, and validation rule."],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1002",
        "category": "access",
        "sentiment": "negative",
        "summary": (
            "Note N-1002 is categorized as access with negative stakeholder tone and a clear "
            "next operational step."
        ),
        "action_items": [
            "Verify workspace state and route the secure access recovery flow.",
            "Acknowledge urgency and provide a clear next update window.",
        ],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1003",
        "category": "integration",
        "sentiment": "negative",
        "summary": (
            "Note N-1003 is categorized as integration with negative stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": [
            "Inspect integration logs and confirm expected payload format.",
            "Acknowledge urgency and provide a clear next update window.",
        ],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1004",
        "category": "data_quality",
        "sentiment": "neutral",
        "summary": (
            "Note N-1004 is categorized as data_quality with neutral stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": ["Compare the source export, report surface, and validation rule."],
        "confidence": 0.58,
    },
    {
        "note_id": "N-1005",
        "category": "feature_request",
        "sentiment": "neutral",
        "summary": (
            "Note N-1005 is categorized as feature_request with neutral stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": [
            "Tag the request for product review and capture the operational use case."
        ],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1006",
        "category": "performance",
        "sentiment": "neutral",
        "summary": (
            "Note N-1006 is categorized as performance with neutral stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": ["Check recent latency signals and escalate with timing evidence."],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1007",
        "category": "process_gap",
        "sentiment": "positive",
        "summary": (
            "Note N-1007 is categorized as process_gap with positive stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": ["Clarify the missing process step and update the operating routine."],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1008",
        "category": "other",
        "sentiment": "neutral",
        "summary": (
            "Note N-1008 is categorized as other with neutral stakeholder tone and a clear "
            "next operational step."
        ),
        "action_items": [],
        "confidence": 0.48,
    },
    {
        "note_id": "N-1009",
        "category": "bug",
        "sentiment": "negative",
        "summary": (
            "Note N-1009 is categorized as bug with negative stakeholder tone and a clear next "
            "operational step."
        ),
        "action_items": [
            "Collect reproduction details and route the failing workflow.",
            "Acknowledge urgency and provide a clear next update window.",
        ],
        "confidence": 0.82,
    },
    {
        "note_id": "N-1010",
        "category": "data_quality",
        "sentiment": "neutral",
        "summary": (
            "Note N-1010 is categorized as data_quality with neutral stakeholder tone and a "
            "clear next operational step."
        ),
        "action_items": ["Compare the source export, report surface, and validation rule."],
        "confidence": 0.82,
    },
]


def test_deterministic_rule_provider_is_deterministic() -> None:
    note = OpsNote.model_validate(
        {
            "id": "N-1",
            "channel": "portal",
            "text": "Webhook sync to the planning dashboard fails during pilot rollout.",
            "created_at": "day_01_09",
        }
    )
    provider = DeterministicRuleProvider()

    first = provider.extract_insight(note)
    second = provider.extract_insight(note)

    assert first == second
    assert OpsInsight.model_validate(first).category == "integration"


def test_characterizes_all_bundled_notes() -> None:
    notes = load_ops_notes(EXAMPLE_NOTES_PATH)
    provider = DeterministicRuleProvider()

    actual = [provider.extract_insight(note) for note in notes]

    assert actual == EXPECTED_INSIGHTS
    # Every payload must still satisfy the schema contract.
    for payload in actual:
        OpsInsight.model_validate(payload)


def test_queued_low_confidence_cases_are_frozen() -> None:
    by_id = {item["note_id"]: item for item in EXPECTED_INSIGHTS}
    notes = {note.id: note for note in load_ops_notes(EXAMPLE_NOTES_PATH)}
    provider = DeterministicRuleProvider()

    for note_id in ("N-1004", "N-1008"):
        assert provider.extract_insight(notes[note_id]) == by_id[note_id]

    assert by_id["N-1004"]["confidence"] == 0.58
    assert by_id["N-1008"]["confidence"] == 0.48


def test_provider_satisfies_insight_protocol() -> None:
    # Structural conformance: the default implementation fills the InsightProvider surface.
    provider: InsightProvider = DeterministicRuleProvider()
    assert callable(provider.extract_insight)
