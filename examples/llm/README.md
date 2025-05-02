# LLMs

**mockstack** can be a great tool for the development of LLM-based flows.

A lot of current applications involve a sort of DAG of API calls to LLM APIs and various "tool" APIs, sometimes serially, sometimes in parallel, and sometimes in a "iterative" fashion (e.g. see [Agents](https://langchain-ai.github.io/langgraph/agents/overview/) documentation on LangGraph website).

you can mock any of these parts out to accelerate development, debugging and integration testing of such workflows.

Mocking out the LLMs themselves can be a particularly effective method to make sure no costs are incurred in early stages of development and in debugging scenarios that don't critically rely on the semantic content of the responses.

This example shows a few possible scenarios involving mockstack and (mostly LangChain-based) LLM workflows.
