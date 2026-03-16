"""
MCP Tools Cache

Provides caching and lazy loading for MCP tools.
"""

import logging
from typing import List, Optional
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

# Global cache
_mcp_tools_cache: Optional[List[BaseTool]] = None
_cache_initialized: bool = False
_config_mtime: Optional[float] = None


def _is_cache_stale() -> bool:
    """Check if cache is stale by comparing config file modification time

    Returns:
        True if cache should be invalidated
    """
    global _config_mtime

    from workflow.mcp.config import get_config_mtime

    current_mtime = get_config_mtime()
    if current_mtime is None:
        return False

    if _config_mtime is None:
        _config_mtime = current_mtime
        return False

    if current_mtime > _config_mtime:
        logger.info("MCP config file modified, invalidating cache")
        _config_mtime = current_mtime
        return True

    return False


def _load_mcp_tools() -> List[BaseTool]:
    """Load MCP tools from configured servers

    Returns:
        List of LangChain BaseTool instances
    """
    tools = []

    try:
        # Import langchain-mcp-adapters (correct import path)
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from workflow.mcp.client import build_servers_config

        servers_config = build_servers_config()

        if not servers_config:
            logger.info("No enabled MCP servers found")
            return []

        # Create MCP client
        logger.info(f"Initializing MCP client with {len(servers_config)} servers")
        client = MultiServerMCPClient(servers_config)

        # Get tools from all servers
        mcp_tools = client.get_tools()
        tools.extend(mcp_tools)

        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

    except ImportError:
        logger.warning(
            "langchain-mcp-adapters not installed. "
            "Install with: pip install langchain-mcp-adapters"
        )
    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}")

    return tools


def initialize_mcp_tools() -> None:
    """Initialize MCP tools cache (called automatically on first access)"""
    global _mcp_tools_cache, _cache_initialized

    if _cache_initialized:
        return

    logger.info("Initializing MCP tools cache")
    _mcp_tools_cache = _load_mcp_tools()
    _cache_initialized = True


def get_cached_mcp_tools() -> List[BaseTool]:
    """Get cached MCP tools (lazy loading + auto refresh)

    Returns:
        List of MCP tools as LangChain BaseTool instances
    """
    global _mcp_tools_cache, _cache_initialized

    # Check if cache is stale
    if _is_cache_stale():
        reset_mcp_tools_cache()

    # Lazy load on first access
    if not _cache_initialized:
        initialize_mcp_tools()

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """Reset MCP tools cache (forces reload on next access)"""
    global _mcp_tools_cache, _cache_initialized, _config_mtime

    logger.info("Resetting MCP tools cache")
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
