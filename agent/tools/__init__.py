"""Built-in tool implementations for the ReAct agent.

The package is split so that reading one tool means reading one directory:

- ``registry``: registration, provider schema adaptation and dispatch
- ``spec`` / ``bindings`` / ``catalog``: the ``ToolSpec`` type, the run-scoped
  ``ToolBindings`` tools are constructed with, and the list of built-in tools
- ``<tool>/``: one package per model-visible tool, **named after that tool**
  (``exec_command/``, ``write_stdin/``, ``read_file/``, ``edit_file/``,
  ``write_file/``, ``code_interpreter/``, ``get_current_time/``,
  ``get_current_temperature/``, ``convert_currency/``). ``__init__.py`` holds the
  package docstring and the public surface, ``spec.py`` declares the tool to the
  registry, and the implementation is split by responsibility
  (``description.py``, ``errors.py``, topic modules, ``tool.py``).
- the remaining modules (``permissions``, ``permission_rules``, ``file_access``,
  ``file_bytes``, ``file_patch``, ``read_ledger``, ``text_encoding``, ``text_lines``,
  ``tokenizers``, ``token_budget``, ``process_group``, ``process_store``,
  ``shell_platform``, ``output_store``) are shared infrastructure and stay at the root.

Keep one tool per package, and name the package after the tool rather than after an
old module name: ``file_read_tool`` is what the tool used to be called, not what the
model calls it.
"""
