"""Built-in tool implementations for the ReAct agent.

The package is split by domain so that each module stays small and focused:

- ``registry``: registration, provider schema adaptation and dispatch
- ``specs``: declarative tool definitions wired into the registry
- ``*_tools``: the concrete implementations
"""
