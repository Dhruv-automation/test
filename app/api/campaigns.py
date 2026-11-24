"""Campaign planning API. Draft creation has no Instagram publishing capability."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.agents.campaign_graph import build_campaign_graph
from app.agents.campaign_models import (
    CampaignPlanDraft,
    CampaignQualityReport,
    CampaignRequest,
)
from app.agents.campaign_planner import (
    CampaignPlanningError,
    OpenAICampaignPlanner,
)
from app.security.runtime_guard import secure_runtime_issue

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignWorkflowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending_approval", "needs_revision"]
    approval_required: Literal[True]
    draft: CampaignPlanDraft
    quality: CampaignQualityReport


@router.post("/plan", response_model=CampaignWorkflowResponse)
def create_campaign_plan(request: CampaignRequest) -> CampaignWorkflowResponse:
    """Create and QA a draft; the result is never published automatically."""
    runtime_issue = secure_runtime_issue()
    if runtime_issue:
        raise HTTPException(status_code=503, detail=runtime_issue)
    try:
        planner = OpenAICampaignPlanner.from_credential_vault()
        final_state = build_campaign_graph(planner).invoke({"request": request})
    except CampaignPlanningError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception:
        # Do not send model/provider internals or user text back through an error page.
        raise HTTPException(status_code=500, detail="Campaign planning workflow failed.") from None

    return CampaignWorkflowResponse(
        status=final_state["status"],
        approval_required=True,
        draft=final_state["draft"],
        quality=final_state["quality"],
    )
