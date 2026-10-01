"""Front Desk inside Claude Code: an agent exists only while someone has a session open.

``server`` is an MCP channel server: it holds the identity's proof, gives the agent its tools and
pushes waking messages into the open session. ``hooks`` are the moments Claude Code provides: a
session starts, a prompt is submitted, a turn finishes, a session ends.
"""
