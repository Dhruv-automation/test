"""LangGraph workflow for draft, QA, and human approval routing."""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.campaign_models import (
    CampaignPlanDraft,
    CampaignQualityReport,
    CampaignRequest,
)
from app.agents.campaign_planner import CampaignPlanner


class CampaignState(TypedDict, total=False):
    request: CampaignRequest
    feedback: list[str]
    attempts: int
    draft: CampaignPlanDraft
    quality: CampaignQualityReport
    approval_required: bool
    status: str


def _quality_review(
    request: CampaignRequest,
    draft: CampaignPlanDraft,
) -> CampaignQualityReport:
    issues: list[str] = []
    suggestions: list[str] = []

    if len(draft.posts) != request.post_count:
        issues.append(
            f"Draft contains {len(draft.posts)} posts; {request.post_count} were requested."
        )

    normalized_captions = [" ".join(post.caption.casefold().split()) for post in draft.posts]
    if len(normalized_captions) != len(set(normalized_captions)):
        issues.append("Posts contain duplicate captions.")

    avoided_topics = [
        topic.casefold().strip()
        for topic in request.brand_profile.topics_to_avoid
        if topic.strip()
    ]
    for post in draft.posts:
        combined = f"{post.topic_angle} {post.hook} {post.caption}".casefold()
        if any(topic in combined for topic in avoided_topics):
            issues.append("A draft mentions a topic listed in the brand profile's avoid list.")
            break
        if not post.hashtags:
            suggestions.append("Add relevant hashtags to each post or confirm that none are wanted.")

    issues = list(dict.fromkeys(issues))
    score = max(0, 100 - (25 * len(issues)) - (5 * len(suggestions)))
    return CampaignQualityReport(score=score, issues=issues, suggestions=suggestions)


def build_campaign_graph(planner: CampaignPlanner):
    """Build a draft-only workflow; no node can publish to Instagram."""

    def plan_campaign(state: CampaignState) -> dict[str, object]:
        attempts = state.get("attempts", 0) + 1
        draft = planner.create_draft(
            state["request"],
            feedback=state.get("feedback", []),
        )
        return {"draft": draft, "attempts": attempts}

    def quality_review(state: CampaignState) -> dict[str, object]:
        report = _quality_review(state["request"], state["draft"])
        return {"quality": report, "feedback": report.issues}

    def route_after_review(state: CampaignState) -> Literal[
        "plan_campaign", "queue_for_approval", "needs_revision"
    ]:
        report = state["quality"]
        if report.score >= 80:
            return "queue_for_approval"
        if state.get("attempts", 0) < 2:
            return "plan_campaign"
        return "needs_revision"

    def queue_for_approval(state: CampaignState) -> dict[str, object]:
        return {"status": "pending_approval", "approval_required": True}

    def needs_revision(_: CampaignState) -> dict[str, object]:
        return {"status": "needs_revision", "approval_required": True}

    builder = StateGraph(CampaignState)
    builder.add_node("plan_campaign", plan_campaign)
    builder.add_node("quality_review", quality_review)
    builder.add_node("queue_for_approval", queue_for_approval)
    builder.add_node("needs_revision", needs_revision)
    builder.add_edge(START, "plan_campaign")
    builder.add_edge("plan_campaign", "quality_review")
    builder.add_conditional_edges(
        "quality_review",
        route_after_review,
        {
            "plan_campaign": "plan_campaign",
            "queue_for_approval": "queue_for_approval",
            "needs_revision": "needs_revision",
        },
    )
    builder.add_edge("queue_for_approval", END)
    builder.add_edge("needs_revision", END)
    return builder.compile()
