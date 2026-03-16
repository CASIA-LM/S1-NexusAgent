#!/usr/bin/env python
"""S1-NexusAgent CLI - AI4Science Research Terminal.

Usage:
    python nexus_cli.py                          # Start interactive session
    python nexus_cli.py -p "分析 BRCA1 蛋白"     # Start with initial prompt
    python nexus_cli.py --thread <id>            # Resume a session
    python nexus_cli.py --auto-approve           # Skip HITL approval
    python nexus_cli.py --mcp-config mcp.json    # Load MCP tools
    python nexus_cli.py --no-conversation-log    # Disable conversation logging

Slash Commands (inside the CLI):
    /help       Show available commands
    /clear      Clear conversation and start new thread
    /tokens     Show token usage
    /threads    Manage conversation threads
    /trace      Show LangSmith trace URL
    /remember   Save context to persistent memory
    /quit       Exit

Logging:
    - System logs: logs/nexus_cli_YYYYMMDD_HHMMSS.log (stdout/stderr)
    - Conversations: logs/conversations/conversation_YYYYMMDD_HHMMSS_<thread>.txt/json
    - Use --no-log-file to disable system logging
    - Use --no-conversation-log to disable conversation logging

Note: Commands like /model, /reload, /compact, and /mcp are not supported
      in S1-NexusAgent due to the fixed multi-node pipeline architecture.
"""

import argparse
import asyncio
import logging
import sys
import os


def _suppress_known_warnings() -> None:
    """Suppress known harmless warnings at startup."""
    # Suppress LangGraph checkpoint deserialization warnings for our Pydantic types.
    # These types are safe to deserialize; the warning is informational noise.
    class _DropCheckpointDeserWarning(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "Deserializing unregistered type" not in record.getMessage()

    logging.getLogger("langgraph.checkpoint.serde.jsonplus").addFilter(
        _DropCheckpointDeserWarning()
    )


def main() -> None:
    """Parse arguments and launch the NexusAgent CLI."""
    _suppress_known_warnings()

    parser = argparse.ArgumentParser(
        description="S1-NexusAgent CLI - AI4Science Research Terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python nexus_cli.py\n"
            "  python nexus_cli.py -p '分析 BRCA1 蛋白结构'\n"
            "  python nexus_cli.py --auto-approve --no-mcp\n"
        ),
    )

    parser.add_argument(
        "-a", "--agent",
        default="nexus",
        help="Agent name for memory/state storage (default: nexus)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve all tool calls (no HITL prompts)",
    )
    parser.add_argument(
        "--thread",
        metavar="ID",
        help="Thread ID to resume a previous session",
    )
    parser.add_argument(
        "-p", "--prompt",
        metavar="TEXT",
        help="Initial prompt to auto-submit on startup",
    )
    parser.add_argument(
        "--mcp-config",
        metavar="PATH",
        help="Path to MCP servers JSON configuration file",
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Disable all MCP tool loading",
    )
    parser.add_argument(
        "--log-dir",
        metavar="PATH",
        default="logs",
        help="Directory to save log files (default: logs)",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default=os.getenv("LOGGER_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO, or LOGGER_LEVEL env var)",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable automatic log file saving",
    )
    parser.add_argument(
        "--no-conversation-log",
        action="store_true",
        help="Disable automatic conversation history logging",
    )

    args = parser.parse_args()

    # 设置自动日志保存
    log_file = None
    original_stdout = None
    original_stderr = None

    if not args.no_log_file:
        from cli.logger_setup import setup_auto_logging
        log_file, original_stdout, original_stderr = setup_auto_logging(
            log_dir=args.log_dir,
            log_level=args.log_level,
            capture_stdout=True,
            capture_stderr=True,
        )
        print(f"\n📝 日志自动保存到: {log_file}\n")

    from cli.main import run_nexus_cli_async

    try:
        asyncio.run(
            run_nexus_cli_async(
                assistant_id=args.agent,
                auto_approve=args.auto_approve,
                thread_id=args.thread,
                initial_prompt=args.prompt,
                mcp_config_path=args.mcp_config,
                no_mcp=args.no_mcp,
                enable_conversation_log=not args.no_conversation_log,
            )
        )
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # 清理日志重定向
        if not args.no_log_file and (original_stdout or original_stderr):
            from cli.logger_setup import cleanup_logging
            cleanup_logging(original_stdout, original_stderr)
            if log_file:
                print(f"\n✅ 完整日志已保存到: {log_file}")


if __name__ == "__main__":
    main()
