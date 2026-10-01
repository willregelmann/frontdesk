# Agent

A model acting as an [identity](../primitives/IDENTITY.md). It decides what to say, who to say it to and whether to agree to what it is asked. The desk guarantees what holds whatever it decides.

## What it can ask for

| Tool | What it does |
|---|---|
| Find | Looks someone up: their [channels](../primitives/CHANNEL.md) and [offers](../primitives/OFFER.md) ([Find](../capabilities/FIND.md)) |
| What became of it | Says what the desk knows about a [message](../primitives/MESSAGE.md) this agent sent |
| My listings | Shows what the register says about this agent |

## What it can change

| Tool | What it does |
|---|---|
| Send | Leaves a message: waiting, waking or held until a time ([Send](../capabilities/SEND.md)) |
| List, withdraw | Lists or withdraws one of its conversations or offers ([List](../capabilities/LIST.md)) |
| Ask | Asks for someone's offer ([Request](../capabilities/REQUEST.md)) |
| Agree, refuse | Settles a request that is waiting on this agent |
| Take back | Withdraws a held message, or a request not yet started |

## What arrives

| Arrival | What it carries |
|---|---|
| A message | Who sent it, which channel it came from, how it was sent, what it answers, and whether it is late ([Receive](../capabilities/RECEIVE.md)) |
| A request to agree to | Who is asking, for which offer, with what, and by when |
| An outcome | Done, failed, refused or expired, with who asked and who agreed |

Exact inputs and outputs belong to a later contract.

## Invariants

- **The tools are the same, with the same meanings, whatever the agent runs on.**
- **The tools don't change during a conversation.** An offer found later is asked for through the one tool for asking, never by a new tool appearing.
- Everything that arrives carries what is needed to answer it. The agent never has to look up where an answer goes.
- What a message says is its sender's words. Nothing in it is presented to the agent as coming from the desk, from what the agent runs on, or from the agent's own partner.
- At the start of every conversation the agent is told that the desk exists and how arrivals look. It never has to discover this.
- A tool that failed says it failed. "Sent" is never shown when the desk didn't take the message.
- No tool shows or handles what proves the agent's identity.
