
import os
import dataclasses
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape



env = Environment(
    loader=FileSystemLoader(os.path.dirname(__file__)),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)

async def apply_prompt_template(prompt_name, **kwargs) -> str:
    """
    Apply template variables to a prompt template and return formatted messages.

    Args:
        prompt_name: Name of the prompt template to use

    Returns:
        system prompt
    """
    state_vars = {
        "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
        **kwargs
    }

    try:
        template = env.get_template(f"{prompt_name}.md")
        system_prompt = template.render(**state_vars)
        return system_prompt
    except Exception as e:
        raise ValueError(f"Error applying template {prompt_name}: {e}")
