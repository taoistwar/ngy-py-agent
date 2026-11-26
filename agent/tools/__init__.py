"""Built-in tool implementations for the ReAct agent.

The package is split so that reading one tool means reading one directory:

- ``registry``: registration, provider schema adaptation and dispatch
- ``spec`` / ``bindings`` / ``catalog``: the ``ToolSpec`` type, the run-scoped
  ``ToolBindings`` tools are constructed with, and the list of built-in tools
- ``<tool>/``: one package per model-visible tool, **named after that tool**
  (``exec_command/``, ``write_stdin/``, ``glob/``, ``grep/``, ``web_search/``,
  ``web_fetch/``, ``web_browser/``, ``read_file/``, ``edit_file/``, ``write_file/``,
  ``delete_file/``, ``code_interpreter/``, ``computer_observe/``,
  ``computer_control/``, ``ask_user_question/``, ``todo_write/``).
  ``__init__.py`` holds the package docstring and the public surface, ``spec.py``
  declares the tool to the registry, and the implementation is split by
  responsibility (``description.py``, ``errors.py``, topic modules, ``tool.py``).
- the remaining modules (``denylist``, ``permissions``, ``permission_rules``, ``file_access``,
  ``file_bytes``, ``file_limits``, ``file_patch``, ``file_walk``, ``glob_pattern``,
  ``read_ledger``, ``text_encoding``, ``text_lines``, ``tokenizers``, ``token_budget``,
  ``process_group``, ``process_store``, ``shell_platform``, ``output_store``,
  ``todo_store``, ``web_urls``) are
  shared infrastructure and stay at the root. ``file_walk`` and ``glob_pattern``
  are shared by ``glob`` and ``grep``, ``file_limits`` by ``read_file`` and
  ``delete_file``, and ``web_urls`` by the URL-reading tools (``web_fetch``,
  ``web_browser``) and the permission gate, precisely because a tool package must
  not import another tool package.
  ``web_search`` deliberately reuses only this root layer: it needs URLs
  (``web_urls``), the output budget (``token_budget``/``output_store``) and text
  decoding (``text_encoding``), never ``web_fetch``'s internals.

Keep one tool per package, and name the package after the tool rather than after an
old module name: ``file_read_tool`` is what the tool used to be called, not what the
model calls it.
"""
