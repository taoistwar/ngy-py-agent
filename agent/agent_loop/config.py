"""Loop-level settings resolved once, at import time."""

import os

from agent.provider import DEFAULT_PROVIDER

# The provider to run when the caller does not name one. The environment variable
# keeps its historical name (it started as the tool-schema selection switch) and the
# fallback is the provider module's default, so there is one place that says what
# "not configured" means.
TOOL_SCHEMA_PROVIDER = os.getenv("TOOL_SCHEMA_PROVIDER") or DEFAULT_PROVIDER
# The only override is the global setting in the settings table, so "not configured" has
# exactly one answer: every caller falls back to this value. There is deliberately no
# environment variable - a second source would mean "not configured" has two.
DEFAULT_MAX_STEPS = 9
