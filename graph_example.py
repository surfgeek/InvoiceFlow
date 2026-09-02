"""Verify local LangGraph execution with a single-node graph."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ExampleState(TypedDict):
    message: str


def acknowledge(state: ExampleState) -> ExampleState:
    return {"message": f"Received: {state['message']}"}


def build_graph():
    builder = StateGraph(ExampleState)
    builder.add_node("acknowledge", acknowledge)
    builder.add_edge(START, "acknowledge")
    builder.add_edge("acknowledge", END)
    return builder.compile()


if __name__ == "__main__":
    graph = build_graph()
    initial_state = {"message": "Hello, InvoiceFlow"}
    print("Input:", initial_state)
    result = graph.invoke(initial_state)
    print("Output:", result)
