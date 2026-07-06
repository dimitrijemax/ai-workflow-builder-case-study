from ai_workflow_builder.providers import FakeLLM
from ai_workflow_builder.schemas import OpsInsight, OpsNote


def test_fake_llm_is_deterministic() -> None:
    note = OpsNote.model_validate(
        {
            "id": "N-1",
            "channel": "portal",
            "text": "Webhook sync to the planning dashboard fails during pilot rollout.",
            "created_at": "day_01_09",
        }
    )
    provider = FakeLLM()

    first = provider.extract_insight(note)
    second = provider.extract_insight(note)

    assert first == second
    assert OpsInsight.model_validate(first).category == "integration"
