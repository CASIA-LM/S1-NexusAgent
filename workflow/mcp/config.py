"""
MCP Configuration Loader

Loads MCP server configurations from extensions_config.json.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


def get_config_path() -> Path:
    """Get the path to extensions_config.json"""
    # Look for config in project root
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "extensions_config.json"
    return config_path


def load_mcp_config() -> Dict[str, Any]:
    """Load MCP server configurations from extensions_config.json

    Returns:
        Dict containing mcpServers configuration, or empty dict if not found
    """
    config_path = get_config_path()

    if not config_path.exists():
        logger.info(f"MCP config file not found at {config_path}, MCP tools disabled")
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        mcp_servers = config.get('mcpServers', {})
        logger.info(f"Loaded MCP config with {len(mcp_servers)} servers")
        return mcp_servers

    except Exception as e:
        logger.error(f"Failed to load MCP config: {e}")
        return {}


def get_enabled_servers() -> Dict[str, Any]:
    """Get only enabled MCP servers from configuration

    Returns:
        Dict of enabled server configurations
    """
    all_servers = load_mcp_config()
    enabled = {
        name: config
        for name, config in all_servers.items()
        if config.get('enabled', False)
    }
    logger.info(f"Found {len(enabled)} enabled MCP servers")
    return enabled


def get_config_mtime() -> Optional[float]:
    """Get modification time of config file for cache invalidation

    Returns:
        Modification timestamp or None if file doesn't exist
    """
    config_path = get_config_path()
    if config_path.exists():
        return config_path.stat().st_mtime
    return None
