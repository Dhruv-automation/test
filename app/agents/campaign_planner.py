"""OpenAI-backed structured campaign drafting."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv

from app.agents.campaign_models import CampaignPlanDraft, CampaignRequest
from app.security.credential_vault import CredentialVault, CredentialVaultError

OPENAI_API_KEY_CREDENTIAL_NAME = "openai_api_key"


class CampaignPlanningError(RuntimeError):
    """Safe, user-facing campaign planning failure."""


class CampaignPlanner(Protocol):
    def create_draft(
        self,
        request: CampaignRequest,
        *,
        feedback: list[str],
    ) -> CampaignPlanDraft: ...


class OpenAICampaignPlanner:
    """Create typed campaign drafts using OpenAI Structured Outputs."""

    def __init__(self, client: object, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_credential_vault(cls) -> "OpenAICampaignPlanner":
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env", override=False)
        try:
            api_key = CredentialVault().get_secret(OPENAI_API_KEY_CREDENTIAL_NAME)
        except CredentialVaultError:
            raise CampaignPlanningError(
                "OpenAI API key is unavailable in Windows Credential Manager."
            ) from None
        if not api_key:
            raise CampaignPlanningError(
                "Store the OpenAI API key in Windows Credential Manager before planning."
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
        except Exception:
            raise CampaignPlanningError("OpenAI client could not be initialized.") from None

        return cls(client, os.getenv("OPENAI_MODEL", "gpt-6.2-astra"))

    def create_draft(
        self,
        request: CampaignRequest,
        *,
        feedback: list[str],
    ) -> CampaignPlanDraft:
        payload = {
            "instruction": request.instruction,
            "requested_post_count": request.post_count,
            "brand_profile": request.brand_profile.model_dump(mode="json"),
            "quality_feedback_to_fix": feedback,
        }
        try:
            response = self._client.responses.parse(  # type: ignore[attr-defined]
                model=self._model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are the Content Director for an Instagram Creator account. "
                            "Create a useful campaign draft that follows the brand profile and "
                            "the requested post count. Do not claim to have researched current "
                            "trends or verified factual claims. Do not schedule or publish. "
                            "Return only the requested structured draft."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                text_format=CampaignPlanDraft,
            )
        except Exception:
            # Provider errors can contain request details; don't surface them to the UI/logs.
            raise CampaignPlanningError("OpenAI campaign drafting failed.") from None

        if response.status != "completed" or response.output_parsed is None:
            raise CampaignPlanningError("OpenAI did not return a complete campaign draft.")
        return response.output_parsed
