"""Skill loader - loads skills from filesystem."""

from pathlib import Path
import yaml
from typing import List, Optional
import logging

from .schemas import Skill, SkillMetadata

logger = logging.getLogger(__name__)


def parse_skill_file(skill_file: Path, category: str) -> Optional[Skill]:
    """Parse a SKILL.md file.

    Args:
        skill_file: Path to SKILL.md file
        category: Skill category (public/custom/evolved)

    Returns:
        Skill object or None if parsing fails
    """
    try:
        content = skill_file.read_text(encoding="utf-8")

        # Split YAML frontmatter and workflow content
        if not content.startswith("---"):
            logger.warning(f"Skill file {skill_file} missing YAML frontmatter")
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"Skill file {skill_file} has invalid format")
            return None

        yaml_content = parts[1]
        workflow_content = parts[2].strip()

        # Parse metadata
        metadata_dict = yaml.safe_load(yaml_content)
        if not metadata_dict:
            logger.warning(f"Skill file {skill_file} has empty metadata")
            return None

        # Add category to metadata
        metadata_dict["category"] = category

        # Create metadata object
        metadata = SkillMetadata(**metadata_dict)

        # Create skill object
        skill = Skill(
            metadata=metadata,
            workflow=workflow_content,
            skill_dir=str(skill_file.parent),
            skill_file=str(skill_file),
        )

        return skill

    except Exception as e:
        logger.error(f"Error parsing skill file {skill_file}: {e}")
        return None


def load_skills(
    skills_path: Path = Path("skills"),
    enabled_only: bool = True,
    categories: List[str] = None,
) -> List[Skill]:
    """Load all skills from filesystem.

    Args:
        skills_path: Root skills directory
        enabled_only: Only load enabled skills
        categories: List of categories to load (default: all)

    Returns:
        List of Skill objects
    """
    if categories is None:
        categories = ["public", "custom", "evolved"]

    skills = []
    category_skill_names = {}

    for category in categories:
        category_path = skills_path / category
        if not category_path.exists():
            logger.debug(f"Category path {category_path} does not exist")
            continue

        if category not in category_skill_names:
            category_skill_names[category] = {}

        # Each subdirectory is a potential skill
        for skill_dir in category_path.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                logger.debug(f"No SKILL.md found in {skill_dir}")
                continue

            skill = parse_skill_file(skill_file, category)
            if skill:
                # Check for duplicate skill names within category
                if skill.metadata.name in category_skill_names[category]:
                    existing_path = category_skill_names[category][skill.metadata.name]
                    raise ValueError(
                        f"Duplicate skill name '{skill.metadata.name}' found in {category} category. "
                        f"Existing: {existing_path}, Duplicate: {skill_file.parent}"
                    )

                category_skill_names[category][skill.metadata.name] = str(skill_file.parent)

                # Filter by enabled status
                if enabled_only and not skill.metadata.enabled:
                    continue

                skills.append(skill)

    logger.info(f"Loaded {len(skills)} skills from {skills_path}")
    return skills
