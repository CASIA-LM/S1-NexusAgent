"""Skill management system for S1-NexusAgent."""

from .schemas import Skill, SkillMetadata, SkillConfig
from .loader import load_skills, parse_skill_file
from .manager import SkillManager
from .integration import build_system_prompt_with_skills, get_skill_manager

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillConfig",
    "load_skills",
    "parse_skill_file",
    "SkillManager",
    "build_system_prompt_with_skills",
    "get_skill_manager",
]
