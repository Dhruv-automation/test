"""Campaign API checks with a fully offline planning stub."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.agents.campaign_models import (
    CampaignPlanDraft,
    CampaignRequest,
    PlannedPost,
)
from app.agents.campaign_planner import CampaignPlanningError
from app.api import campaigns


class FixedPlanner:
    def create_draft(self, request: CampaignRequest, *, feedback: list[str]) -> CampaignPlanDraft:
        return CampaignPlanDraft(
            title="Testing fundamentals",
            objective="Share practical testing advice.",
            schedule_summary="Two drafts, dates to be selected after approval.",
            posts=[
                PlannedPost(
                    format="carousel",
                    topic_angle="Risk-based test design",
                    hook="Test the highest-risk path first.",
                    caption="Prioritize tests using impact and likelihood of failure.",
                    call_to_action="Save this idea.",
                    hashtags=["#qa", "#testing"],
                    visual_brief="A short risk matrix with clear labels.",
                ),
                PlannedPost(
                    format="reel",
                    topic_angle="Readable automation checks",
                    hook="Make the assertion easy to understand.",
                    caption="Clear assertions help the next engineer debug a failure.",
                    call_to_action="Share with your QA team.",
                    hashtags=["#testautomation"],
                    visual_brief="A short screen-free storyboard with three steps.",
                ),
            ],
        )


def _request() -> CampaignRequest:
    return CampaignRequest(
        instruction="Make two practical posts for QA engineers about software testing.",
        post_count=2,
        brand_profile={"name": "Quality Notes", "target_audience": "QA engineers"},
    )


def test_campaign_api_returns_draft_waiting_for_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = FixedPlanner()
    monkeypatch.setattr(
        campaigns.OpenAICampaignPlanner,
        "from_credential_vault",
        classmethod(lambda cls: planner),
    )

    result = campaigns.create_campaign_plan(_request())

    assert result.status == "pending_approval"
    assert result.approval_required is True
    assert len(result.draft.posts) == 2


def test_campaign_api_reports_missing_ai_credential_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_planner(cls: type) -> FixedPlanner:
        raise CampaignPlanningError("Store the OpenAI API key in Windows Credential Manager first.")

    monkeypatch.setattr(
        campaigns.OpenAICampaignPlanner,
        "from_credential_vault",
        classmethod(no_planner),
    )

    with pytest.raises(HTTPException) as exc_info:
        campaigns.create_campaign_plan(_request())

    assert exc_info.value.status_code == 503
    assert "Windows Credential Manager" in str(exc_info.value.detail)


def test_campaign_api_rejects_unpatched_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        campaigns,
        "secure_runtime_issue",
        lambda: "Campaign planning is disabled on this Python build.",
    )

    with pytest.raises(HTTPException) as exc_info:
        campaigns.create_campaign_plan(_request())

    assert exc_info.value.status_code == 503
    assert "disabled on this Python build" in str(exc_info.value.detail)
