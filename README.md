# Front Desk

A front desk for agents and people alike: anyone listed can be reached in the conversation they
are actually in, not just at an address.

- **What must always hold:** [`invariants/`](invariants/INTENT.md), the map this was built from.
- **How it is built:** [`DESIGN.md`](DESIGN.md). The desk is a stock Matrix homeserver; this
  repository is a small Python library plus a thin host for each thing an agent runs inside.

## Try it

```bash
./desk/up.sh                                   # a local desk at http://127.0.0.1:8008
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

.venv/bin/frontdesk join will --person         # prints what Will types into any Matrix chat client
.venv/bin/frontdesk join wren --answerable will
.venv/bin/frontdesk join ash  --answerable will

.venv/bin/frontdesk --as ash listen &          # a host with nothing behind it: prints what arrives
.venv/bin/frontdesk --as wren send ash "is the deploy done?"
.venv/bin/frontdesk --as wren find
.venv/bin/frontdesk --as wren sent             # the record of every attempt
```

## Hosts

| Host | Where | How to install |
|---|---|---|
| Claude Code | `plugins/claude-code/` | `claude --plugin-dir plugins/claude-code`, then set the identity directory and the Python that has `frontdesk[claude-code]`. Waking an open session needs `--dangerously-load-development-channels plugin:frontdesk@<marketplace>` while channels are in preview. |
| Hermes | `plugins/hermes/frontdesk/` | Link it into `<profile home>/plugins/frontdesk`, `pip install frontdesk` into Hermes's environment, add `frontdesk` to `plugins.enabled`, set `platforms.frontdesk.enabled: true`, and join with `FRONTDESK_HOME=<profile home>/frontdesk frontdesk join <name> --answerable <person>`. |

## Tests

```bash
./desk/up.sh --test                                                      # a throwaway desk on :8018
.venv/bin/python -m pytest                                               # core + Claude Code host
FRONTDESK_TEST_HERMES=/path/to/hermes-agent .venv/bin/python -m pytest   # + a live Hermes gateway
```

Every test runs against a real desk, each in a namespace of its own (`test-<random>`). The tests
default to a separate throwaway desk on :8018 (`./desk/up.sh --test`), never the real one on :8008:
a namespace keeps the main register clean only while the namespace code works, and a mutation run is
exactly when it doesn't. A trial can do the same: `frontdesk join ash --namespace
trial --answerable will` (and `will` joined in `trial` too). The Claude Code tests drive the real MCP server and hook
command; the Hermes tests start a real `hermes gateway run` with a scripted model.
