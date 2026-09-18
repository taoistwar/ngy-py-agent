"""Built-in tool implementations for the ReAct agent.

The package is split by domain so that each module stays small and focused:

- ``registry``: registration, provider schema adaptation and dispatch
- ``specs``: declarative tool definitions wired into the registry
- ``*_tools`` / ``*_tool``: the concrete implementations

Keep one tool per module. When a domain grows beyond a single tool (for example
file read / write / edit), give each tool its own module such as
``file_read_tool`` instead of growing a single ``file_tools`` module.
"""
