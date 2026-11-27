"""HTTP route packages: one module per route group.

Each module owns one ``APIRouter`` (``task_api``, ``workspace_api``, ``llm_api``,
``agent_api``, ``tool_api``, ``admin_api``, ``memory_api``, ``mcp_api``). They are mounted by ``main``,
which is the only module allowed to depend on them - a route module reads live state
through ``commons.state`` and task logic through ``agent.runtime``, never through ``main``.
"""
