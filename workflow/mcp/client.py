"""
MCP Client Builder

Builds MultiServerMCPClient parameters from configuration.
"""

import os
import logging
from typing import Dict, Any, List
from workflow.mcp.config import get_enabled_servers

logger = logging.getLogger(__name__)


def expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in configuration values

    Args:
        value: Configuration value (str, dict, list, or other)

    Returns:
        Value with environment variables expanded
    """
    if isinstance(value, str):
        # Replace $VAR_NAME with environment variable value
        if value.startswith('$'):
            env_var = value[1:]
            return os.getenv(env_var, value)
        return value
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def build_server_params(server_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Build MCP server parameters from configuration

    Args:
        server_name: Name of the MCP server
        config: Server configuration dict

    Returns:
        Parameters dict for MultiServerMCPClient
    """
    transport_type = config.get('type', 'stdio')
    params = {'transport': transport_type}

    if transport_type == 'stdio':
        params['command'] = config.get('command', '')
        params['args'] = config.get('args', [])
        params['env'] = expand_env_vars(config.get('env', {}))

    elif transport_type in ('http', 'sse', 'streamable_http'):
        params['url'] = config.get('url', '')
        params['headers'] = expand_env_vars(config.get('headers', {}))

        # Handle OAuth if configured
        oauth_config = config.get('oauth')
        if oauth_config and oauth_config.get('enabled'):
            params['oauth'] = expand_env_vars(oauth_config)

    logger.debug(f"Built params for MCP server '{server_name}': transport={transport_type}")
    return params


def build_servers_config() -> Dict[str, Dict[str, Any]]:
    """Build configuration for all enabled MCP servers

    Returns:
        Dict mapping server names to their parameters
    """
    enabled_servers = get_enabled_servers()
    servers_config = {}

    for server_name, config in enabled_servers.items():
        try:
            params = build_server_params(server_name, config)
            servers_config[server_name] = params
            logger.info(f"Configured MCP server: {server_name}")
        except Exception as e:
            logger.error(f"Failed to configure MCP server '{server_name}': {e}")

    return servers_config
