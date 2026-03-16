"""Skill match output schema definition."""

from typing import Optional
from pydantic import BaseModel, Field


class SkillMatchResult(BaseModel):
    """Skill matching result schema.

    Used by the skill_match_node to determine if a user query matches
    any available skill workflow.
    """

    matched_skill: Optional[str] = Field(
        default=None,
        description="Name of the matched skill (if any). None if no skill matches."
    )

    reasoning: str = Field(
        description="Explanation of why this skill was matched or why no skill matched."
    )
