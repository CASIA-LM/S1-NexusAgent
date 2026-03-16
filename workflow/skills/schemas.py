"""Skill data models."""

from pydantic import BaseModel, Field
from typing import Literal, Optional


class SkillMetadata(BaseModel):
    """Skill metadata from YAML frontmatter."""

    name: str = Field(description="Skill name")
    description: str = Field(description="Skill description")
    category: Literal["public", "custom", "evolved"] = Field(description="Skill category")
    enabled: bool = Field(default=True, description="Whether skill is enabled")
    version: str = Field(default="1.0.0", description="Skill version")
    author: Optional[str] = Field(default=None, description="Skill author")
    tags: list[str] = Field(default_factory=list, description="Skill tags")


class Skill(BaseModel):
    """Complete skill definition."""

    metadata: SkillMetadata
    workflow: str = Field(description="Workflow instructions (markdown content)")
    skill_dir: str = Field(description="Skill directory path")
    skill_file: str = Field(description="SKILL.md file path")


class SkillConfig(BaseModel):
    """Skill configuration in config file."""

    enabled: bool = Field(default=True, description="Whether skill is enabled")
