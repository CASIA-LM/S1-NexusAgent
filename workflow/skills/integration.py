"""Helper functions to integrate skills into the workflow graph."""

from datetime import datetime
from workflow.skills import SkillManager


def build_system_prompt_with_skills(
    base_prompt: str,
    skill_manager: SkillManager = None,
    enabled_only: bool = True
) -> str:
    """Build system prompt with skills section.

    Args:
        base_prompt: Base system prompt
        skill_manager: SkillManager instance (creates new if None)
        enabled_only: Only include enabled skills

    Returns:
        System prompt with skills section
    """
    if skill_manager is None:
        skill_manager = SkillManager()

    # Get skills section
    skills_section = skill_manager.format_skills_for_prompt(enabled_only=enabled_only)

    if not skills_section:
        return base_prompt

    # Add skills section and instructions
    skills_instructions = """

# Skills System

You have access to specialized skills that provide workflow guidance for complex tasks.

{skills_section}

## How to Use Skills

When a user's request matches a skill description:
1. Identify the relevant skill from the <skill_system> list above
2. Use the read_file tool to load the skill's SKILL.md file from the location specified
3. Follow the workflow instructions in the SKILL.md file
4. Use available tools to complete the task according to the skill's guidance
5. Report results to the user

Skills provide structured workflows for common scientific tasks. Always check if a skill is available before starting a complex task.
"""

    return base_prompt + skills_instructions.format(skills_section=skills_section)


def get_skill_manager() -> SkillManager:
    """Get or create global skill manager instance.

    Returns:
        SkillManager instance
    """
    global _skill_manager
    if "_skill_manager" not in globals():
        _skill_manager = SkillManager()
    return _skill_manager
