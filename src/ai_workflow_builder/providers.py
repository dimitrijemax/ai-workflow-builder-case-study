from __future__ import annotations

from typing import Any, Protocol

from ai_workflow_builder.schemas import InsightCategory, OpsNote, Sentiment


class InsightProvider(Protocol):
    def extract_insight(self, note: OpsNote) -> dict[str, Any]:
        """Return a raw structured payload that must still be schema-validated."""


class DeterministicRuleProvider:
    """Deterministic offline rule provider for demos and tests."""

    def extract_insight(self, note: OpsNote) -> dict[str, Any]:
        text = note.text.lower()
        category = self._category(text)
        sentiment = self._sentiment(text)
        confidence = self._confidence(text, category)
        action_items = self._action_items(category, sentiment)

        return {
            "note_id": note.id,
            "category": category.value,
            "sentiment": sentiment.value,
            "summary": self._summary(note, category, sentiment),
            "action_items": action_items,
            "confidence": confidence,
        }

    def _category(self, text: str) -> InsightCategory:
        rules = [
            (
                InsightCategory.DATA_QUALITY,
                ["mismatch", "source export", "headcount", "validation", "source field"],
            ),
            (InsightCategory.ACCESS, ["login", "access", "locked", "workspace", "admin"]),
            (InsightCategory.INTEGRATION, ["api", "webhook", "sync", "integration"]),
            (InsightCategory.BUG, ["error", "broken", "fails", "reload"]),
            (InsightCategory.FEATURE_REQUEST, ["feature", "export", "filter", "group"]),
            (InsightCategory.DOCUMENTATION, ["docs", "guide", "unclear", "instructions"]),
            (InsightCategory.PERFORMANCE, ["slow", "latency", "timeout"]),
            (
                InsightCategory.PROCESS_GAP,
                ["rollout", "mapping", "handoff", "unclear process", "operating routine"],
            ),
        ]
        for category, keywords in rules:
            if any(keyword in text for keyword in keywords):
                return category
        return InsightCategory.OTHER

    def _sentiment(self, text: str) -> Sentiment:
        negative_words = ["blocked", "angry", "frustrated", "urgent", "cannot", "fails"]
        positive_words = ["thanks", "helpful", "works", "great"]
        if any(word in text for word in negative_words):
            return Sentiment.NEGATIVE
        if any(word in text for word in positive_words):
            return Sentiment.POSITIVE
        return Sentiment.NEUTRAL

    def _confidence(self, text: str, category: InsightCategory) -> float:
        if category == InsightCategory.OTHER:
            return 0.48
        if "maybe" in text or "unclear" in text:
            return 0.58
        return 0.82

    def _summary(
        self,
        note: OpsNote,
        category: InsightCategory,
        sentiment: Sentiment,
    ) -> str:
        return (
            f"Note {note.id} is categorized as {category.value} with "
            f"{sentiment.value} stakeholder tone and a clear next operational step."
        )

    def _action_items(self, category: InsightCategory, sentiment: Sentiment) -> list[str]:
        if category == InsightCategory.OTHER:
            return []
        actions = {
            InsightCategory.ACCESS: (
                "Verify workspace state and route the secure access recovery flow."
            ),
            InsightCategory.BUG: "Collect reproduction details and route the failing workflow.",
            InsightCategory.INTEGRATION: (
                "Inspect integration logs and confirm expected payload format."
            ),
            InsightCategory.FEATURE_REQUEST: (
                "Tag the request for product review and capture the operational use case."
            ),
            InsightCategory.DOCUMENTATION: (
                "Update the knowledge note or send the relevant guide section."
            ),
            InsightCategory.PERFORMANCE: (
                "Check recent latency signals and escalate with timing evidence."
            ),
            InsightCategory.DATA_QUALITY: (
                "Compare the source export, report surface, and validation rule."
            ),
            InsightCategory.PROCESS_GAP: (
                "Clarify the missing process step and update the operating routine."
            ),
        }
        item = actions.get(category, "Ask a clarifying question and update the note record.")
        if sentiment == Sentiment.NEGATIVE:
            return [item, "Acknowledge urgency and provide a clear next update window."]
        return [item]
