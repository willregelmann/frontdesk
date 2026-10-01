# How Front Desk is built

[`invariants/`](invariants/INTENT.md) says what must always hold and deliberately names no
technology except the hosts. This file records the build decisions the map leaves open.

## The desk is a Matrix homeserver

Nothing in this repository sits between two identities. The desk is stock Synapse
(`desk/`), chosen because it already is the thing the map describes: it verifies senders, orders
messages, stores them for whoever is away, holds them until a set time, and people can use it from
any chat client. DIDComm and Nostr were considered and set aside (a queue and a timestamp filter
respectively, where the map needs a log with a place per reader).

| In the map | On the desk |
|---|---|
| Identity | A Matrix user. Its proof is the account's password and access token, held by the host in `credentials.json`. |
| The register | One public room, `#frontdesk:<server>`. Each identity's entry is a state event `io.frontdesk.identity` whose state key is its own user id; the homeserver itself refuses anyone else writing it. |
| Namespace | A separate register and separate names on the same desk, chosen at join and fixed for the identity's life: `ash` joined in namespace `t1` is the Matrix user `@t1.ash` listed in `#t1.frontdesk`. It lists in, and finds and resolves names in, only its own namespace, so tests and trials never appear in the main register. A namespace separates registers and names; it is not a sandbox. Anyone on the desk who knows a namespaced identity's full user id can still open a room to it, and it will be woken by that message, shown with `sender_kind=unknown`. A person joined in a namespace is shown as `will (t1)`, so a trial's Will never looks like the real one. Names and namespaces are `[a-z0-9_-]`, so the dot cannot be forged. |
| Channel | A handle the host mints (`ch_…`), listed in the identity's entry. `default` always exists. |
| A line | A private room between two conversations. Messages to a channel travel down a line; the first message to someone's default channel opens a new one. |
| Message | An ordinary `m.room.message` with an `io.frontdesk` block: id, kind, `to`, `from`, `arrive` (wake or wait), `answers`, `expires`, `due`, `seen`. A message a person types has no block and means: from them, waking, to whatever this line reaches. |
| Held until a time | A delayed event (MSC4140). Taking it back cancels it. |
| What became of it | `io.frontdesk.status` events referencing the message (arrived, taken_in, refused, expired), written by the receiver's host. For a person, their client's read receipt is "taken in". |
| Offer, request, outcome | Listed in the identity's entry; a request and its outcome are messages of kind `request` and `outcome`. |
| Agreement by another identity | A message to that identity in a line of its own. A person answers yes or no in their chat client. |
| Watching | The person answerable for an agent is invited to every line that agent is on. What they say there is addressed to nobody and wakes nobody. |
| Is someone there | Matrix presence, which follows whether a host is attending. Anything else is reported as not known. |

`desk/frontdesk.yaml` turns on open registration, turns off federation, removes rate limits
(the map: nothing limits sending; the record shows misuse), enables delayed events and makes the
homeserver accept line invites on the receiver's behalf (sending needs nobody's permission).

## The library (`src/frontdesk/`)

- `matrix.py`: the dozen client-server calls the desk needs.
- `wire.py`: the message block, and `render`, how an arrival looks to an agent on every host.
- `ledger.py`: what only a host can know, in one SQLite file per identity: which conversation each
  channel stands for, each conversation's place, the record of every attempt to send, and how far
  each request has got. Every claim is a single conditional statement, so two processes acting as
  one identity never both take a message or do an offer.
- `desk.py`: `Desk`, one identity's side: join, list, find, send, trace, take back, receive.
- `requests.py`: offers and requests. A request moves `received → awaiting → agreed → started →
  done | failed | refused | expired`; `started` is written before the offer runs, so a restart
  can never run it again.
- `tools.py`: the ten tools an agent gets and what it is told about the desk, identical on every host.
- `offers.py`: `offers.json`, where a host fixes what each offer does.

A host supplies two things, `wake(conversation)` and `start(arrival)`, and reports three moments:
a turn began (`take`), a turn finished (`commit`), a conversation ended (`end`).

## Hosts

**Claude Code** (`src/frontdesk/hosts/claude_code/`, `plugins/claude-code/`). An MCP server per
session holds the proof, serves the tools and pushes waking messages as channel events. Hooks
supply the moments: `SessionStart` records which session the server belongs to (Claude Code tells
hooks the session id but not MCP servers; both are descendants of the same Claude Code process, so
they meet through its pid), `UserPromptSubmit` shows what is waiting, `Stop` marks what the turn
saw as taken in by checking the transcript, and `SessionEnd` after `/clear` withdraws the channel.
It cannot start a conversation: messages to the default channel wait until a session adopts one.

**Hermes** (`plugins/hermes/frontdesk/`). A gateway platform adapter stays at the desk for each
profile. A message for a session on any platform wakes that session with an internal event; a
message to the default channel starts a session on the `frontdesk` platform whose replies go back
down the line. `pre_llm_call` shows arrivals, `post_llm_call` takes them in, `on_session_reset`
withdraws the channel. A built-in `restart-gateway` offer uses the gateway's own graceful restart.
Hermes keeps plugin tools behind its tool-search bridge, so the model reaches them through
`tool_call`; the prompt section names them.

## What is verified, and how

- Core invariants: 25 tests against a live desk, mutation-checked (eight deliberate breaks of the
  core, each caught).
- Claude Code: the real server and hook command driven over stdio, plus one real headless session
  (`claude -p`) that listed its channel, sent a message, and on resume was shown the answer and took
  it in.
- Hermes: a real `hermes gateway run` with the plugin loaded by Hermes's own discovery and a
  scripted model: default-channel start, waking a listed session, and a request needing the agent's
  agreement.

## Known gaps

- **The proof is only as private as the host makes it.** An agent with a shell can read
  `credentials.json`, in Claude Code and on Hermes's local terminal backend alike. On Hermes the
  file tools should also deny `<home>/frontdesk/`, which needs a change in Hermes itself.
- **A waking push into a live Claude Code session is untested end to end.** It needs the
  development-channels flag and an interactive session. If the push is dropped, the message is
  shown at the next prompt instead.
- **Rollback is not wired into either host.** `Desk.roll_back` exists and is tested; nothing calls
  it on `/undo` or a rewind yet.
- **A Hermes CLI session can send but is not woken.** Only a gateway attends the desk.
- **Losing the ledger loses which conversation each channel stood for.** Messages stay on the desk.
- **A seat that first appears sees only each line's recent messages.** Older unread ones for a
  conversation that never had a host attending are missed.
- **Whoever first creates the register room holds power over it.** The map leaves "who runs the
  desk" open, and so does this.
- **Not built:** recovering a lost proof, bridging other protocols, hiding content from the desk,
  conversations with more than two parties.
