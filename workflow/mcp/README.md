# MCP Integration for NexusAgent

## Quick Start

### 1. Install Dependencies

```bash
pip install langchain-mcp-adapters
```

### 2. Configure MCP Servers

Edit `extensions_config.json` in project root:

```json
{
  "mcpServers": {
    "filesystem": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "description": "Local filesystem access"
    }
  }
}
```

### 3. Use in CodeAct

MCP tools are automatically loaded and can be called in `<execute>` blocks:

```python
<execute>
# Call MCP filesystem tool
content = filesystem_read(path="/tmp/data.csv")

# Process with pandas
import pandas as pd
df = pd.read_csv(io.StringIO(content))
print(df.head())
</execute>
```

## Features

- ✅ **CodeAct Compatible**: Call MCP tools as Python functions in code
- ✅ **Auto Loading**: MCP tools loaded automatically in tool retrieval phase
- ✅ **Hot Reload**: Config changes detected and reloaded automatically
- ✅ **Unified Interface**: MCP tools work like built-in tools

## Architecture

```
Tool Retrieval → [Domain Tools + MCP Tools] → Planner → Executor (CodeAct)
                                                              │
                                                              ▼
                                                    Sandbox executes code
                                                    calling MCP tools
```

## Documentation

See [MCP_INTEGRATION_GUIDE.md](./MCP_INTEGRATION_GUIDE.md) for detailed documentation.

## Module Structure

```
workflow/mcp/
├── __init__.py      # Module exports
├── cache.py         # Tool caching with hot reload
├── client.py        # MCP client builder
└── config.py        # Configuration loader
```

## Key Implementation Points

### 1. Tool Loading (graph.py:421-445)

```python
# Load MCP tools in retrieval_tools_node
from workflow.mcp.cache import get_cached_mcp_tools
mcp_tools = get_cached_mcp_tools()

# Merge with domain tools
for tool in mcp_tools:
    final_tool_map[tool.name] = tool
```

### 2. Sandbox Compatibility

MCP tools are passed to code agent as LangChain `BaseTool` instances:
- Tools are available in sandbox execution environment
- Agent calls them as Python functions
- MCP protocol communication handled transparently

### 3. Cache Management

- **Lazy loading**: Tools loaded on first access
- **Config monitoring**: File mtime checked for changes
- **Auto refresh**: Cache invalidated when config modified

## Example: Combining MCP with Code

```python
<execute>
# 1. Read files with MCP filesystem tool
files = ['gene1.csv', 'gene2.csv']
dfs = [pd.read_csv(io.StringIO(filesystem_read(path=f"/data/{f}")))
       for f in files]

# 2. Process with pandas
combined = pd.concat(dfs)
top_genes = combined.nlargest(10, 'expression')

# 3. Create GitHub issue with MCP github tool
github_create_issue(
    repo="lab/analysis",
    title="Top Genes Found",
    body=top_genes.to_markdown()
)
</execute>
```

## Supported Transport Types

- **stdio**: Local process communication (Node.js MCP servers)
- **http**: Remote REST API
- **sse**: Server-Sent Events (long-lived connections)

## Environment Variables

Use `$VAR_NAME` in config to reference environment variables:

```json
{
  "headers": {
    "Authorization": "Bearer $GITHUB_TOKEN"
  }
}
```

## Troubleshooting

### MCP tools not loading

1. Check `extensions_config.json` exists in project root
2. Verify `enabled: true` for servers
3. Install `langchain-mcp-adapters`: `pip install langchain-mcp-adapters`
4. Check logs for error messages

### stdio server fails

1. Ensure Node.js installed
2. Test command manually: `npx -y @modelcontextprotocol/server-filesystem /tmp`
3. Check environment variables set correctly

## Benefits

1. **Unified Execution Model**: Everything runs through CodeAct
2. **Natural Integration**: MCP tools called like regular Python functions
3. **Flexible**: Easy to add new tools via configuration
4. **Powerful**: Access to entire MCP ecosystem

## Comparison with Separate Tool Calling

| Aspect | MCP in CodeAct ✅ | Separate Tool Calls ❌ |
|--------|------------------|----------------------|
| Execution Model | Unified (code only) | Dual (code + tool_call) |
| Data Processing | Easy (Python code) | Complex (message passing) |
| Tool Composition | Natural | Difficult |
| Agent Complexity | Low | High |

## Next Steps

1. Enable MCP servers in `extensions_config.json`
2. Install required MCP server packages
3. Test with simple filesystem operations
4. Explore official MCP servers: https://github.com/modelcontextprotocol

---

**Note**: MCP integration maintains full compatibility with existing CodeAct workflow. No changes needed to prompts or execution logic.
