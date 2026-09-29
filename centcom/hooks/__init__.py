"""Ready-made hooks that report every tool call to Contro1, per framework.

Each module imports its framework only when used, so ``centcom`` stays free of
them:

    from centcom.hooks.langchain import Contro1TraceHandler       # LangChain, LangGraph
    from centcom.hooks.openai_agents import Contro1RunHooks       # OpenAI Agents SDK
    from centcom.hooks.strands import Contro1HookProvider         # Strands Agents

All three are built on ``centcom.tracing.TraceRun`` and take ``fail_closed``:
when set, a tool whose start Contro1 could not record does not run.
"""
