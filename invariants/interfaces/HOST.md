# Host

What an [agent](AGENT.md) runs inside. There are two. In Hermes something is always running, and it can start a conversation by itself. In Claude Code an agent exists only while someone has a session open.

## Moments the host provides

| Moment | What the desk does with it |
|---|---|
| A conversation starts | It can be listed as a [channel](../primitives/CHANNEL.md) |
| A turn finishes | Arrived [messages](../primitives/MESSAGE.md) are taken up, and the reader's place moves |
| A conversation is shortened or resumed | Nothing: its channel still reaches it |
| A conversation is rolled back | Its place goes back with it |
| A conversation ends | Its channel is withdrawn |
| The host restarts | Each conversation carries on from its place |
| Nothing is running | Messages wait |

## What the host does for the desk

| Job | Hermes | Claude Code |
|---|---|---|
| Holds what proves the [identity](../primitives/IDENTITY.md) | Yes | Yes |
| Starts a turn for a waking message | Yes | While a session is open |
| Shows waiting messages when a conversation is next active | Yes | Yes |
| Starts a fresh conversation for the default channel | Yes | No: the message waits |
| Carries out what an [offer](../primitives/OFFER.md) does | Yes | While a session is open |

## Invariants

- **The desk behaves the same on every host. Where a host can't do something, the message waits and its state says so.** A host never pretends.
- **The host, never the model, holds the proof of identity and carries out an offer.**
- A host that restarts skips nothing and does nothing twice. That holds when the offer being done is restarting the host itself.
- Arriving messages are added at the end of a conversation, at a point where a new turn could begin, and nowhere else.
- A message for one conversation is never shown in another conversation of the same identity.
- When a host stops without saying so, its conversations become "not known to be there". They are never shown as there.
