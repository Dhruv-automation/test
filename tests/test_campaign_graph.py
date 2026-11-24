"""Offline tests for the LangGraph campaign planning workflow."""

from __future__ import annotations

from app.agents.campaign_graph import build_campaign_graph
from app.agents.campaign_models import (
    CampaignPlanDraft,
    CampaignRequest,
    PlannedPost,
)


def _request() -> CampaignRequest:
    return CampaignRequest(
        instruction="Create two educational posts about software testing.",
        post_count=2,
        brand_profile={
            "name": "Quality Notes",
            "target_audience": "QA engineers",
            "tone": "clear and practical",
            "topics_to_avoid": ["unverified guarantees"],
        },
    )


def _valid_draft() -> CampaignPlanDraft:
    return CampaignPlanDraft(
        title="Practical testing ideas",
        objective="Help QA engineers improve everyday test coverage.",
        schedule_summary="Two posts during the week; dates await approval.",
        posts=[
            PlannedPost(
                format="carousel",
                topic_angle="A risk-based test checklist",
                hook="Start with the failures that matter most.",
                caption="A practical checklist can help teams focus test effort on high-risk paths.",
                call_to_action="Save this checklist for your next review.",
                hashtags=["#softwaretesting", "#qa"],
                visual_brief="Five clean checklist slides using the brand palette.",
            ),
            PlannedPost(
                format="single_image",
                topic_angle="Making flaky tests easier to diagnose",
                hook="A flaky test is a signal worth investigating.",
                caption="Record the environment and failure pattern before changing the test.",
                call_to_action="Share your debugging approach.",
                hashtags=["#testautomation", "#qualityengineering"],
                visual_brief="A simple diagnostic flow with three steps.",
            ),
        ],
    )


class QueuePlanner:
    def __init__(self, drafts: list[CampaignPlanDraft]) -> None:
        self.drafts = drafts
        self.feedback_seen: list[list[str]] = []

    def create_draft(self, request: CampaignRequest, *, feedback: list[str]) -> CampaignPlanDraft:
        self.feedback_seen.append(feedback)
        return self.drafts.pop(0)


def test_campaign_graph_queues_valid_drafts_for_human_approval() -> None:
    graph = build_campaign_graph(QueuePlanner([_valid_draft()]))

    result = graph.invoke({"request": _request()})

    assert result["status"] == "pending_approval"
    assert result["approval_required"] is True
    assert result["quality"].score == 100
    assert "published" not in result


def test_campaign_graph_retries_once_with_qa_feedback() -> None:
    bad = _valid_draft().model_copy(
        update={"posts": [_valid_draft().posts[0], _valid_draft().posts[0]]}
    )
    planner = QueuePlanner([bad, _valid_draft()])
    graph = build_campaign_graph(planner)

    result = graph.invoke({"request": _request()})

    assert len(planner.feedback_seen) == 2
    assert planner.feedback_seen[0] == []
    assert "duplicate captions" in planner.feedback_seen[1][0]
    assert result["status"] == "pending_approval"


def test_campaign_graph_stops_for_manual_revision_after_retry_limit() -> None:
    bad = _valid_draft().model_copy(
        update={"posts": [_valid_draft().posts[0], _valid_draft().posts[0]]}
    )
    result = build_campaign_graph(QueuePlanner([bad, bad])).invoke(
        {"request": _request()}
    )

    assert result["status"] == "needs_revision"
    assert result["approval_required"] is True
