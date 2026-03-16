# S1-NexusAgent

**S1-NexusAgent** is an open-source AI agent framework for scientific research, built on [LangGraph](https://github.com/langchain-ai/langgraph). It provides a multi-node reasoning pipeline with 130+ domain-specific tools covering biology, chemistry, and materials science.

> **Note:** This project is in active development. APIs and interfaces may change between releases.

---

## Features

- **Multi-node LangGraph pipeline** — Intent detection → Tool retrieval → Planning → Execution → Report generation
- **130+ scientific tools** — Biology (genomics, proteomics, CRISPR), Chemistry (drug-likeness, molecular fingerprints), Materials Science (Materials Project integration)
- **Intelligent tool retrieval** — Embedding-based semantic search selects the right tools per query
- **Code execution sandbox** — Optional remote sandbox for running Python/R analysis scripts
- **MCP tool support** — Connect external tools via Model Context Protocol
- **Observability** — Optional Langfuse tracing integration
- **Interactive CLI** — Rich terminal interface with conversation history and HITL approval

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/CASIA-LM/S1-NexusAgent.git
cd S1-NexusAgent
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.template .env
# Edit .env — at minimum set DEEPSEEK_API_KEY and EMBEDDING_API_KEY
```

The two keys required to get started:

| Variable | Description |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key (primary LLM) |
| `EMBEDDING_API_KEY` | API key for the embedding model (tool retrieval) |

See [.env.template](.env.template) for the full list of optional variables.

### 3. Start the sandbox

The code execution sandbox lets the agent run Python/R analysis scripts. It uses a pre-built Docker image — no manual build or image upload needed.

```bash
docker-compose -f docker-compose.sandbox.yml up -d
```

This pulls `ghcr.io/agent-infra/sandbox:latest` and exposes it on `localhost:9001`, which matches the default `SANDBOX_URL` in `.env`.

> **Skip this step** if you do not need code execution. The agent will still run without it.

### 4. Run

```bash
# Interactive CLI
python nexus_cli.py

# One-shot query
python nexus_cli.py -p "Analyze BRCA1 gene mutations and their association with breast cancer risk"
```

---

## Project Structure

```
S1-NexusAgent/
├── nexus_cli.py          # CLI entry point
├── workflow/
│   ├── graph.py          # LangGraph workflow definition
│   ├── config.py         # Model & service configuration (env-based)
│   ├── state.py          # Workflow state schema
│   ├── const.py          # Constants (node names, tool IDs)
│   ├── tool_retriever.py # Embedding-based tool selection
│   ├── codeact_remote.py # Remote code execution client
│   ├── nodes/            # Individual node implementations
│   │   ├── intent.py     # Intent/task-type classification
│   │   ├── retrieval.py  # Tool retrieval node
│   │   ├── planner.py    # Task planning node
│   │   ├── execute.py    # Tool execution node
│   │   └── report.py     # Report generation node
│   ├── tools/            # Domain-specific scientific tools
│   │   ├── biology.py
│   │   ├── bio_genomics.py
│   │   ├── bio_genetics.py
│   │   ├── normal.py     # General tools (web search, image)
│   │   ├── math.py       # Mathematical computation tools
│   │   ├── chemistry/    # Chemistry tools
│   │   └── material/     # Materials science tools
│   ├── prompt/           # Prompt templates (Markdown)
│   └── utils/            # Shared utilities
├── cli/                  # CLI helper modules
├── docker/               # Docker Compose configuration
├── .env.template         # Environment variable template
└── requirements.txt      # Python dependencies
```

---

## Workflow Architecture

![S1-NexusAgent Architecture](image/architecture.png)

---

## Configuration

All configuration is done via environment variables. No secrets are hardcoded in the source.

### Required

| Variable | Description | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API key | _(empty)_ |
| `DEEPSEEK_BASE_URL` | API endpoint | `https://api.deepseek.com/v1` |


### Optional

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_URL` | `http://localhost:9001` | Code execution sandbox URL — start via `docker-compose -f docker-compose.sandbox.yml up -d` |
| `TAVILY_API_KEY` | _(empty)_ | Web search (Tavily) |
| `MP_API_KEY` | _(empty)_ | Materials Project API |
| `LANGFUSE_SECRET_KEY` | _(empty)_ | Langfuse tracing secret key |
| `LANGFUSE_PUBLIC_KEY` | _(empty)_ | Langfuse tracing public key |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | Langfuse endpoint (cloud or self-hosted) |

---


## CLI Usage

```bash
python nexus_cli.py                          # Interactive session
python nexus_cli.py -p "your query"          # Start with a prompt
```

**In-session slash commands:**

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/clear` | Start a new conversation thread |
| `/tokens` | Show token usage statistics |
| `/threads` | List and manage conversation threads |
| `/remember` | Save context to persistent memory |
| `/quit` | Exit |

---

## Requirements

- Python 3.12+
- At minimum one LLM API key (DeepSeek recommended) and one embedding model API key
- Optional: Docker (for code execution sandbox)

---

## Docker

A Docker Compose configuration is provided for running the full stack:

```bash
# Copy and configure environment
cp .env.template .env
# Edit .env with your API keys

docker-compose -f docker/docker-compose.yml up -d
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Open a Pull Request

For major changes, please open an issue first to discuss the approach.

---

## License

[Apache License 2.0](LICENSE)

---

## Acknowledgments

Built with:
- [LangGraph](https://github.com/langchain-ai/langgraph) — workflow orchestration
- [LangChain](https://github.com/langchain-ai/langchain) — LLM integration
- [DeepSeek](https://www.deepseek.com/) — primary LLM
- Biopython, RDKit, pymatgen, and many other scientific computing libraries
