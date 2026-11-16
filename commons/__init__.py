"""What the HTTP layer and the task runtime share: the live state and the request models.

Layering rule: ``commons`` may import ``agent`` and ``dao``; nothing in those two may
import it back, with one recorded exception (ADR 0025) - ``agent.runtime``,
``agent.usage`` and ``agent.history`` execute and report on a task, so they read the
live state. ``agent.tools`` and ``agent.agent_loop`` stay free of it (ADR 0019).

This module deliberately re-exports nothing: importing ``commons`` must not drag
``commons.state`` (which builds every store) into a process that only wants the schemas.
"""
