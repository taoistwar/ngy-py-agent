"""The agent engine: the ReAct loop, providers, tools, checkpoints and telemetry.

Layering rule (ADR 0025): ``agent.agent_loop`` and ``agent.tools`` must not import
``commons`` or ``dao`` - a tool has to be testable without the web admin's state. The
task lifecycle pieces do read that state: ``agent.runtime`` runs a task, ``agent.history``
rebuilds the session transcript and ``agent.usage`` reports what a run cost.

This module deliberately re-exports nothing. A re-export here would import the whole
engine (including ``agent.runtime`` -> ``commons.state``) whenever a single submodule is
imported, which is how the ``commons``/``agent`` cycle would become a real one.
"""
