"""NexusAgent Textual CLI application.

Subclasses DeepAgentsApp to inherit all UI features (slash commands, streaming,
HITL approval, MCP viewer, etc.) while using the NexusAgent graph as the
primary agent.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from rich.syntax import Syntax
from rich.text import Text
from textual.widgets import Static, Markdown

from deepagents_cli.app import DeepAgentsApp
from deepagents_cli.config import newline_shortcut
from deepagents_cli.widgets.messages import (
    AppMessage,
    AssistantMessage,
    ErrorMessage,
    UserMessage,
)

from cli.conversation_logger import ConversationLogger

logger = logging.getLogger(__name__)

# ── Node icons for pipeline progress ──────────────────────────────────────
_NODE_ICONS = {
    "TalkCheck": "\u2714",      # ✔
    "Intent": "\u2696",         # ⚖
    "ToolRetrieval": "\U0001F50D",  # 🔍
    "Preplanner": "\U0001F4CB",     # 📋
    "Planner": "\U0001F9E0",        # 🧠
    "Execute": "\u26A1",        # ⚡
    "Report": "\U0001F4C4",         # 📄
}


class NexusAgentsApp(DeepAgentsApp):
    """S1-NexusAgent CLI application.

    Inherits Deep Agents CLI infrastructure with customizations:
    - Textual UI with rich rendering
    - HITL approval for tool calls
    - Session/thread management
    - @file references
    - !command shell execution
    - Automatic conversation logging

    Supported slash commands:
    - /quit, /q: Exit the application
    - /clear: Clear conversation and start new thread
    - /tokens: Show token usage statistics
    - /threads: View and switch conversation threads
    - /trace: Show LangSmith trace URL (if configured)
    - /remember: Save context to persistent memory
    - /help: Show help message

    Disabled commands (incompatible with fixed graph architecture):
    - /model: Model switching requires graph rebuild
    - /reload: Config reload requires graph rebuild
    - /compact: Use /clear instead
    - /mcp: Not configured

    Overrides:
    - Title branding
    - Command handling (_handle_slash_command)
    - Model switching (_switch_model, disabled)
    - Agent task execution (_run_agent_task, custom streaming)
    """

    TITLE = "S1-NexusAgent"

    def __init__(self, *args, enable_conversation_log: bool = True, **kwargs):
        """初始化 NexusAgentsApp。

        Args:
            enable_conversation_log: 是否启用对话历史记录
        """
        super().__init__(*args, **kwargs)
        self._conversation_logger: ConversationLogger | None = None
        self._enable_conversation_log = enable_conversation_log

        # 初始化对话记录器
        if self._enable_conversation_log:
            thread_id = kwargs.get("thread_id", "unknown")
            self._conversation_logger = ConversationLogger(
                log_dir="logs/conversations",
                thread_id=thread_id,
                format="both",  # 同时保存 txt 和 json
            )

    # Custom CSS for NexusAgent-specific widgets
    CSS = """
    .nexus-progress {
        height: auto;
        padding: 0 1;
        margin: 0 0;
        color: #6b7280;
    }
    .nexus-subtask {
        height: auto;
        padding: 0 2;
        margin: 1 0;
        border-left: wide #a855f7;
    }
    .nexus-tools {
        height: auto;
        padding: 0 2;
        margin: 0 0;
        color: #6b7280;
    }
    .nexus-plan {
        height: auto;
        padding: 0 2;
        margin: 1 0;
        border-left: wide #3b82f6;
    }
    .nexus-execute-header {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
        border-left: wide #f59e0b;
    }
    .nexus-exec-code {
        height: auto;
        padding: 0 2;
        margin: 0 0 1 2;
        border-left: wide #f59e0b;
    }
    .nexus-exec-think {
        height: auto;
        padding: 0 2;
        margin: 1 0 1 2;
        border-left: wide #8b5cf6;
        color: #a78bfa;
    }
    .nexus-exec-text {
        height: auto;
        padding: 0 2;
        margin: 0 0 0 2;
        color: #9ca3af;
    }
    .nexus-exec-observe {
        height: auto;
        padding: 0 2;
        margin: 1 0 1 2;
        border-left: wide #10b981;
    }
    .nexus-exec-solution {
        height: auto;
        padding: 0 2;
        margin: 0 0 0 2;
        border-left: wide #22c55e;
    }
    .nexus-execute-done {
        height: auto;
        padding: 0 2;
        margin: 0 0 1 0;
        border-left: wide #10b981;
    }
    .nexus-report-header {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    """

    async def _switch_model(
        self,
        model_spec: str,
        *,
        extra_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Override model switching.

        NexusAgent uses fixed model configuration defined in workflow/config.py.
        Runtime model switching is disabled to maintain consistency across the
        multi-node pipeline (different nodes may use different models).
        """
        await self._mount_message(
            AppMessage(
                "NexusAgent uses fixed model config (different nodes use different models).\n"
                "Edit workflow/config.py to change model assignments.\n\n"
                "Current node model mapping:\n"
                "  talk_check / intent / normal_chat -> DeepSeekV3\n"
                "  preplanner / planner / execute    -> DeepSeekV3_2\n"
                "  reflection / report / summary     -> DeepSeekV3 / DeepSeekV3_2"
            )
        )

    # ── Custom command handling ───────────────────────────────────────────

    async def _handle_slash_command(self, command: str) -> None:
        """Handle slash commands with S1-NexusAgent customizations.

        Disables commands that are incompatible with the fixed graph architecture:
        - /model: Model switching requires graph rebuild
        - /reload: Config reload requires graph rebuild
        - /compact: Needs verification with custom graph state
        - /mcp: Not used in current configuration

        Customizes /help to show only supported commands.
        """
        cmd = command.lower().strip()

        # Disabled commands - provide helpful feedback
        if cmd in {"/model"} or cmd.startswith("/model "):
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                AppMessage(
                    "Command /model is not supported in S1-NexusAgent.\n"
                    "NexusAgent uses a fixed multi-model configuration where different "
                    "nodes use different models.\n"
                    "To change model assignments, edit workflow/config.py and restart the CLI."
                )
            )
            return

        if cmd in {"/reload"}:
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                AppMessage(
                    "Command /reload is not supported in S1-NexusAgent.\n"
                    "Configuration changes require rebuilding the agent graph.\n"
                    "Please restart the CLI to apply configuration changes."
                )
            )
            return

        if cmd in {"/compact"}:
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                AppMessage(
                    "Command /compact is not supported in S1-NexusAgent.\n"
                    "Use /clear to start a new conversation thread instead."
                )
            )
            return

        if cmd in {"/mcp"}:
            await self._mount_message(UserMessage(command))
            await self._mount_message(
                AppMessage(
                    "Command /mcp is not supported in S1-NexusAgent.\n"
                    "MCP server integration is not configured for this agent."
                )
            )
            return

        # Custom /help command
        if cmd == "/help":
            await self._mount_message(UserMessage(command))
            help_text = Text(
                "S1-NexusAgent Commands:\n"
                "  /quit, /q       Exit the application\n"
                "  /clear          Clear conversation and start new thread\n"
                "  /tokens         Show token usage statistics\n"
                "  /threads        View and switch conversation threads\n"
                "  /trace          Show LangSmith trace URL (if configured)\n"
                "  /remember       Save context to persistent memory\n"
                "  /help           Show this help message\n\n"
                "Interactive Features:\n"
                "  Enter           Submit your message\n"
                f"  {newline_shortcut():<15} Insert newline\n"
                "  Shift+Tab       Toggle auto-approve mode\n"
                "  @filename       Auto-complete files and inject content\n"
                "  !command        Run shell commands directly\n\n"
                "Note: S1-NexusAgent uses a fixed multi-node pipeline with specialized models.\n"
                "Commands like /model, /reload, /compact, and /mcp are not supported.",
                style="dim italic",
            )
            await self._mount_message(AppMessage(help_text))
            return

        # For all other commands, use parent implementation
        await super()._handle_slash_command(command)

    # ── Custom streaming handler ──────────────────────────────────────────

    async def _run_agent_task(self, message: str) -> None:
        """Run the NexusAgent graph with custom visual rendering.

        Overrides the parent's _run_agent_task to use stream_mode=["updates", "custom"]
        which properly captures our multi-node pipeline's structured events
        (via get_stream_writer) and renders them with distinct visual styles.
        """
        if self._ui_adapter is None:
            return

        # 记录用户消息
        if self._conversation_logger:
            self._conversation_logger.log_user_message(message)

        # Show thinking spinner
        if self._ui_adapter._set_spinner:
            await self._ui_adapter._set_spinner("Thinking")

        # Execute stream buffer for tag-aware parsing
        self._exec_buffer = ""
        self._current_assistant_content = ""  # 累积 assistant 的完整回复
        self._execute_content_buffer = ""  # 累积 execute 节点的完整内容（用于日志）

        try:
            thread_id = getattr(self._session_state, "thread_id", str(uuid.uuid4()))
            from workflow.graph import get_traced_run_config
            config = get_traced_run_config(
                base_config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 200,
                },
                session_id=thread_id,
            )

            stream_input = {"messages": [{"role": "user", "content": message}]}

            async for mode, data in self._agent.astream(
                stream_input,
                stream_mode=["updates", "custom"],
                config=config,
            ):
                if mode == "custom":
                    await self._render_custom_event(data)
                elif mode == "updates":
                    if isinstance(data, dict):
                        await self._render_updates(data)

        except Exception as e:
            logger.exception("NexusAgent task failed")
            error_msg = str(e)
            await self._mount_message(ErrorMessage(error_msg))
            # 记录错误
            if self._conversation_logger:
                self._conversation_logger.log_system_message(f"错误: {error_msg}", event_type="error")
        finally:
            # Flush any remaining execute buffer
            if self._exec_buffer:
                await self._flush_exec_buffer()

            # 保存累积的 assistant 回复
            if self._conversation_logger and self._current_assistant_content:
                self._conversation_logger.log_assistant_message(self._current_assistant_content)
                self._current_assistant_content = ""

            if self._ui_adapter and self._ui_adapter._set_spinner:
                await self._ui_adapter._set_spinner(None)
            await self._cleanup_agent_task()

    # ── Event renderers ───────────────────────────────────────────────────

    async def _render_custom_event(self, data: dict) -> None:
        """Render a structured custom stream event from a graph node."""
        event_type = data.get("type", "")
        node = data.get("node", "")
        content = data.get("content", "")
        icon = _NODE_ICONS.get(node, "\u2022")  # bullet fallback

        # 记录节点事件（但跳过 execute_stream 和 execute_done，因为它们会被合并为 execute_content）
        if self._conversation_logger and content and event_type not in ("execute_stream", "execute_done"):
            self._conversation_logger.log_node_event(node, event_type, content)

        if event_type == "progress":
            # Dim progress line: ✔ TalkCheck  检测为科学研究任务...
            text = Text()
            text.append(f" {icon} ", style="bold cyan")
            text.append(f"{node}", style="bold cyan")
            text.append(f"  {content}", style="dim")
            await self._mount_message(Static(text, classes="nexus-progress"))
            await self._scroll_chat_bottom()

        elif event_type == "tools":
            # Tool list
            tools_list = data.get("tools", [])
            text = Text()
            text.append(f" {icon} ", style="bold cyan")
            text.append(f"{node}", style="bold cyan")
            text.append(f"  {content}", style="dim")
            if tools_list:
                text.append("\n    ", style="")
                text.append(", ".join(tools_list[:8]), style="dim italic")
                if len(tools_list) > 8:
                    text.append(f" ... +{len(tools_list) - 8} more", style="dim")
            await self._mount_message(Static(text, classes="nexus-tools"))
            await self._scroll_chat_bottom()

        elif event_type == "plan":
            # Plan with numbered steps
            steps = data.get("steps", [])
            text = Text()
            text.append(f" {icon} ", style="bold blue")
            text.append(f"{node}", style="bold blue")
            text.append(f"  {content}\n", style="")
            for i, step in enumerate(steps, 1):
                text.append(f"    {i}. ", style="bold")
                text.append(f"{step}\n", style="")
            await self._mount_message(Static(text, classes="nexus-plan"))
            await self._scroll_chat_bottom()

        elif event_type == "subtask":
            # Subtask dispatch card
            iteration = data.get("iteration", "")
            text = Text()
            text.append(f" {icon} ", style="bold magenta")
            text.append(f"Subtask", style="bold magenta")
            if iteration:
                text.append(f" #{iteration}", style="bold magenta")
            text.append(f"\n    {content}", style="")
            await self._mount_message(Static(text, classes="nexus-subtask"))
            await self._scroll_chat_bottom()

        elif event_type == "execute_start":
            # Start execution section
            if self._ui_adapter and self._ui_adapter._set_spinner:
                await self._ui_adapter._set_spinner("Executing")
            text = Text()
            text.append(f" {icon} ", style="bold yellow")
            text.append("Executing", style="bold yellow")
            text.append(f"  {content[:120]}", style="dim")
            await self._mount_message(Static(text, classes="nexus-execute-header"))
            await self._scroll_chat_bottom()

            # Initialize buffer for tag-aware streaming
            self._exec_buffer = ""
            # 初始化 execute 内容缓冲区（用于日志）
            self._execute_content_buffer = ""

        elif event_type == "execute_stream":
            # Buffer chunks and parse <execute>/<think>/<solution> tags
            if content:
                self._exec_buffer += content
                # 累积到日志缓冲区
                self._execute_content_buffer += content
                await self._process_exec_buffer()

        elif event_type == "execute_done":
            # Flush remaining buffer and finalize
            await self._flush_exec_buffer()

            # 记录完整的 execute 内容到日志
            if self._conversation_logger and self._execute_content_buffer:
                self._conversation_logger.log_node_event(
                    "Execute",
                    "execute_content",
                    self._execute_content_buffer.strip()
                )
                self._execute_content_buffer = ""

            if self._ui_adapter and self._ui_adapter._set_spinner:
                await self._ui_adapter._set_spinner("Thinking")

        elif event_type == "report":
            # Final report - render as full markdown
            if self._ui_adapter and self._ui_adapter._set_spinner:
                await self._ui_adapter._set_spinner(None)

            title = data.get("title", "Report")
            url = data.get("url", "")

            # 累积 assistant 内容
            if content:
                self._current_assistant_content += f"\n\n## {title}\n\n{content}"

            # Report header
            text = Text()
            text.append(f" {icon} ", style="bold green")
            text.append(f"Report: {title}", style="bold green")
            if url:
                text.append(f"\n    {url}", style="dim underline")
            await self._mount_message(Static(text, classes="nexus-report-header"))
            await self._scroll_chat_bottom()

            # Report body as markdown
            report_msg = AssistantMessage(content, id=f"report-{uuid.uuid4().hex[:8]}")
            await self._mount_message(report_msg)
            await report_msg.write_initial_content()
            await self._scroll_chat_bottom()

    # ── Execute stream tag parser ────────────────────────────────────────

    _TAG_DEFS = [
        ("<think>", "</think>", "think"),
        ("<execute>", "</execute>", "execute"),
        ("<observe>", "</observe>", "observe"),
        ("<solution>", "</solution>", "solution"),
    ]

    async def _process_exec_buffer(self) -> None:
        """Parse buffered execute stream for complete tag pairs.

        ONLY renders when a complete <tag>...</tag> pair is found.
        Text before the tag is rendered as a batch. Content inside an
        unclosed tag stays in the buffer until the closing tag arrives.
        This prevents one-token-per-line rendering.
        """
        while True:
            # Find the earliest complete tag pair in the buffer
            best = None  # (start, end_of_close_tag, tag_name, inner_content)

            for open_tag, close_tag, name in self._TAG_DEFS:
                start = self._exec_buffer.find(open_tag)
                if start == -1:
                    continue
                end = self._exec_buffer.find(close_tag, start + len(open_tag))
                if end == -1:
                    continue  # Tag opened but not closed yet — wait
                end_full = end + len(close_tag)
                if best is None or start < best[0]:
                    inner = self._exec_buffer[start + len(open_tag):end]
                    best = (start, end_full, name, inner)

            if best is None:
                # No complete tag pairs found.
                # DON'T render anything — leave buffer as-is.
                # Content will be rendered when:
                #   1. A closing tag arrives → complete pair found next call
                #   2. execute_done → _flush_exec_buffer renders remainder
                break

            start, end_full, tag_name, inner = best

            # Render any plain text BEFORE this tag (batched, not per-token)
            if start > 0:
                text_before = self._exec_buffer[:start].strip()
                if text_before:
                    await self._render_exec_text(text_before)

            # Render the tag content with appropriate styling
            inner = inner.strip()
            if inner:
                if tag_name == "execute":
                    await self._render_exec_code(inner)
                elif tag_name == "think":
                    await self._render_exec_think(inner)
                elif tag_name == "observe":
                    await self._render_exec_observe(inner)
                elif tag_name == "solution":
                    await self._render_exec_solution(inner)

            # Advance buffer past this complete tag
            self._exec_buffer = self._exec_buffer[end_full:]

    async def _flush_exec_buffer(self) -> None:
        """Flush remaining buffer on execute_done. Renders everything left."""
        if not self._exec_buffer:
            return
        # Final pass for any remaining complete tags
        await self._process_exec_buffer()
        # Render whatever is still left, stripping any orphaned tags
        remaining = self._exec_buffer.strip()
        if remaining:
            cleaned = re.sub(
                r'</?(?:think|execute|observe|solution)>',
                '', remaining,
            ).strip()
            if cleaned:
                await self._render_exec_text(cleaned)
        self._exec_buffer = ""

    async def _render_exec_code(self, code: str) -> None:
        """Render <execute> code with Python syntax highlighting."""
        syntax = Syntax(
            code,
            "python",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
        )
        await self._mount_message(Static(syntax, classes="nexus-exec-code"))
        await self._scroll_chat_bottom()

    async def _render_exec_think(self, content: str) -> None:
        """Render <think> reasoning with purple border."""
        text = Text()
        text.append("💭 Thinking:\n", style="bold #8b5cf6")
        text.append(content, style="#a78bfa")
        await self._mount_message(Static(text, classes="nexus-exec-think"))
        await self._scroll_chat_bottom()

    async def _render_exec_observe(self, output: str) -> None:
        """Render <observe> sandbox execution output."""
        text = Text()
        text.append("Output:\n", style="bold green")
        # Truncate very long output for display
        display = output if len(output) <= 2000 else output[:1000] + "\n...[truncated]...\n" + output[-500:]
        text.append(display, style="")
        await self._mount_message(Static(text, classes="nexus-exec-observe"))
        await self._scroll_chat_bottom()

    async def _render_exec_text(self, content: str) -> None:
        """Render plain text commentary from the execute stream."""
        text = Text(content, style="dim")
        await self._mount_message(Static(text, classes="nexus-exec-text"))
        await self._scroll_chat_bottom()

    async def _render_exec_solution(self, content: str) -> None:
        """Render <solution> final answer."""
        text = Text()
        text.append("Solution: ", style="bold green")
        text.append(content, style="")
        await self._mount_message(Static(text, classes="nexus-exec-solution"))
        await self._scroll_chat_bottom()

    async def _scroll_chat_bottom(self) -> None:
        """Scroll the chat area to the bottom after layout refresh."""
        def do_scroll():
            try:
                from textual.widgets import VerticalScroll
                chat = self.query_one("#chat", VerticalScroll)
                if chat.max_scroll_y > 0:
                    chat.scroll_end(animate=False)
            except Exception:
                pass

        # Schedule scroll after the next refresh to ensure layout is updated
        self.call_after_refresh(do_scroll)

    async def on_unmount(self) -> None:
        """在应用卸载时完成对话记录。"""
        if self._conversation_logger:
            self._conversation_logger.finalize()
            log_files = self._conversation_logger.get_log_files()
            logger.info(f"对话历史已保存: {log_files}")
        await super().on_unmount()

    async def _render_updates(self, data: dict) -> None:
        """Render node state updates from the 'updates' stream mode.

        Currently used as a fallback for nodes that don't emit custom events.
        The normal_chat node returns AIMessage directly via state updates.
        """
        for node_name, state_update in data.items():
            if node_name == "__interrupt__":
                continue
            if not isinstance(state_update, dict):
                continue

            # Handle normal_chat response (general node)
            messages = state_update.get("messages")
            if node_name == "unknown_general" and messages:
                # normal_chat returns AIMessage
                from langchain_core.messages import AIMessage
                if isinstance(messages, list):
                    for msg in messages:
                        if isinstance(msg, AIMessage) and msg.content:
                            # 累积 assistant 内容
                            if msg.content:
                                self._current_assistant_content += msg.content

                            report_msg = AssistantMessage(
                                msg.content,
                                id=f"chat-{uuid.uuid4().hex[:8]}",
                            )
                            await self._mount_message(report_msg)
                            await report_msg.write_initial_content()
                            await self._scroll_chat_bottom()
                elif isinstance(messages, AIMessage) and messages.content:
                    # 累积 assistant 内容
                    if messages.content:
                        self._current_assistant_content += messages.content

                    report_msg = AssistantMessage(
                        messages.content,
                        id=f"chat-{uuid.uuid4().hex[:8]}",
                    )
                    await self._mount_message(report_msg)
                    await report_msg.write_initial_content()
                    await self._scroll_chat_bottom()

                if self._ui_adapter and self._ui_adapter._set_spinner:
                    await self._ui_adapter._set_spinner(None)
