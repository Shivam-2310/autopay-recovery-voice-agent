"""LangGraph brain for the autopay recovery agent.

Simple ReAct loop: chatbot ↔ tools, with a loop-count safety guard.
The compiled graph is consumed by livekit-plugins-langchain's LLMAdapter.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = 5


class AgentState(MessagesState):
    """Extended state with a loop counter to prevent infinite tool cycles."""

    loop_count: int


def _should_continue(state: AgentState) -> str:
    """Route after the chatbot node: call tools, or end.

    Returns "tools" if the last message has tool calls AND we haven't hit
    the loop limit. Otherwise returns END.
    """
    messages = state["messages"]
    if not messages:
        return END

    last = messages[-1]
    loop = state.get("loop_count", 0)

    if isinstance(last, AIMessage) and last.tool_calls and loop < MAX_TOOL_LOOPS:
        return "tools"

    if loop >= MAX_TOOL_LOOPS:
        logger.warning("Loop count exceeded %d, forcing end", MAX_TOOL_LOOPS)

    return END


def build_graph(llm: BaseChatModel, tools: list[Any]) -> Any:
    """Construct and compile the ReAct agent graph.

    Args:
        llm: A LangChain chat model (from llm.py's get_llm).
        tools: List of LangChain @tool functions.

    Returns:
        A compiled LangGraph StateGraph ready for LLMAdapter.
    """
    llm_with_tools = llm.bind_tools(tools)

    def chatbot(state: AgentState) -> dict[str, Any]:
        """Invoke the LLM and increment the loop counter."""
        response = llm_with_tools.invoke(state["messages"])
        return {
            "messages": [response],
            "loop_count": state.get("loop_count", 0) + 1,
        }

    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", ToolNode(tools))

    # Edges
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "chatbot")

    compiled = graph.compile()
    logger.info("LangGraph compiled: nodes=%s", list(compiled.nodes.keys()))
    return compiled
