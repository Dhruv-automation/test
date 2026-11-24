"""Validated request and result schemas for campaign planning."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ContentFormat(StrEnum):
    SINGLE_IMAGE = "single_image"
    CAROUSEL = "carousel"
    REEL = "reel"


class BrandProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    target_audience: str = Field(default="", max_length=500)
    tone: str = Field(default="educational and engaging", max_length=120)
    language: str = Field(default="English", max_length=80)
    topics_to_cover: list[str] = Field(default_factory=list, max_length=30)
    topics_to_avoid: list[str] = Field(default_factory=list, max_length=30)
    visual_identity: str = Field(default="", max_length=1000)
    hashtag_strategy: str = Field(default="", max_length=500)


class CampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=10, max_length=4000)
    post_count: int = Field(ge=1, le=12)
    brand_profile: BrandProfile


class PlannedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ContentFormat
    topic_angle: str = Field(min_length=3, max_length=240)
    hook: str = Field(min_length=3, max_length=300)
    caption: str = Field(min_length=10, max_length=2200)
    call_to_action: str = Field(min_length=2, max_length=160)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    visual_brief: str = Field(min_length=5, max_length=1000)


class CampaignPlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=160)
    objective: str = Field(min_length=5, max_length=500)
    schedule_summary: str = Field(min_length=3, max_length=500)
    posts: list[PlannedPost] = Field(min_length=1, max_length=12)


class CampaignQualityReport(BaseModel):
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
