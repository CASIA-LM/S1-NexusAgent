"""Skill manager - manages skill configuration and loading."""

from pathlib import Path
from typing import List, Optional
import json
import logging

from .loader import load_skills
from .schemas import Skill, SkillConfig

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages skills and their configuration."""

    def __init__(
        self,
        skills_path: Path = Path("skills"),
        config_path: Path = Path("config/skills_config.json"),
    ):
        self.skills_path = skills_path
        self.config_path = config_path
        self._skills_cache: Optional[List[Skill]] = None
        self._config_cache: Optional[dict] = None

    def load_config(self) -> dict:
        """Load skill configuration from file."""
        if self._config_cache is not None:
            return self._config_cache

        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                self._config_cache = json.load(f)
        else:
            self._config_cache = {"skills": {}}

        return self._config_cache

    def save_config(self, config: dict):
        """Save skill configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)
        self._config_cache = config

    def get_skill_key(self, skill_name: str, category: str) -> str:
        """Get unique key for a skill.

        Uses format '{category}:{name}' to avoid conflicts.
        """
        return f"{category}:{skill_name}"

    def is_skill_enabled(self, skill_name: str, category: str) -> bool:
        """Check if a skill is enabled.

        Checks new format first ({category}:{name}), then falls back to
        old format ({name}) for backward compatibility.
        """
        config = self.load_config()
        skill_key = self.get_skill_key(skill_name, category)

        # Check new format first
        if skill_key in config.get("skills", {}):
            return config["skills"][skill_key].get("enabled", True)

        # Backward compatibility: check old format for public skills
        if category == "public" and skill_name in config.get("skills", {}):
            return config["skills"][skill_name].get("enabled", True)

        # Default to enabled
        return True

    def set_skill_enabled(self, skill_name: str, category: str, enabled: bool):
        """Set skill enabled status."""
        config = self.load_config()
        skill_key = self.get_skill_key(skill_name, category)

        if "skills" not in config:
            config["skills"] = {}

        config["skills"][skill_key] = {"enabled": enabled}
        self.save_config(config)
        self._skills_cache = None  # Clear cache

    def get_all_skills(self, enabled_only: bool = True) -> List[Skill]:
        """Get all skills.

        Args:
            enabled_only: Only return enabled skills

        Returns:
            List of Skill objects
        """
        if self._skills_cache is None or not enabled_only:
            self._skills_cache = load_skills(skills_path=self.skills_path, enabled_only=False)

        if enabled_only:
            return [
                skill
                for skill in self._skills_cache
                if self.is_skill_enabled(skill.metadata.name, skill.metadata.category)
            ]

        return self._skills_cache

    def get_skill(self, skill_name: str, category: Optional[str] = None) -> Optional[Skill]:
        """Get a specific skill.

        Args:
            skill_name: Name of the skill
            category: Optional category filter

        Returns:
            Skill object or None
        """
        skills = self.get_all_skills(enabled_only=False)

        if category:
            return next(
                (
                    s
                    for s in skills
                    if s.metadata.name == skill_name and s.metadata.category == category
                ),
                None,
            )

        # If no category specified, find all matching skills
        matching_skills = [s for s in skills if s.metadata.name == skill_name]
        if len(matching_skills) == 1:
            return matching_skills[0]
        elif len(matching_skills) > 1:
            raise ValueError(
                f"Multiple skills found with name '{skill_name}'. "
                f"Please specify category. Available: {[s.metadata.category for s in matching_skills]}"
            )

        return None

    def format_skills_for_prompt(self, enabled_only: bool = True) -> str:
        """Format skills list for system prompt.

        Returns XML-formatted skill list similar to DeerFlow.
        """
        skills = self.get_all_skills(enabled_only=enabled_only)

        if not skills:
            return ""

        skill_blocks = []
        for skill in skills:
            skill_block = f"""  <skill name="{skill.metadata.name}">
    description: {skill.metadata.description}
    category: {skill.metadata.category}
    location: {skill.skill_file}
  </skill>"""
            skill_blocks.append(skill_block)

        return f"""<skill_system>
{chr(10).join(skill_blocks)}
</skill_system>"""

    def reload_skills(self):
        """Reload skills from filesystem."""
        self._skills_cache = None
        self._config_cache = None
        logger.info("Skills reloaded")
