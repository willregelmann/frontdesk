# Connectors

Where another messaging system plugs into the desk, so that its conversations can be [channels](../primitives/CHANNEL.md): a chat service people already use, such as Google Chat or Matrix, or another agent protocol. On the other side is that system. A connector carries [messages](../primitives/MESSAGE.md) between it and the desk, and decides nothing about them.

## What passes

| Direction | What crosses |
|---|---|
| In | A message someone sent in that system, with who the system says sent it |
| Out | A message for a channel the connector carries |
| Read | Whatever that system can tell about a message having been read |
| Listing | A conversation in that system becoming a channel, or ending |

## Invariants

- **Every connector gives the same desk.** A message, its states, its sender and its answers mean the same whichever connector carries them. Adding a connector adds no kind of message, channel or [identity](../primitives/IDENTITY.md), and no new tool for an [agent](AGENT.md).
- **A connector says in advance how it knows who sent a message, and how it knows a message was taken in.** A sender it can't verify is shown as unverified. A read it can't see is never reported as taken in.
- A connector reaches only conversations listed as channels. A conversation the connector can see is not reachable until it's listed.
- A channel is carried by exactly one connector at a time.
- A message that came through a connector says which one, and says plainly when its sender couldn't be verified.
- A connector that stops leaves its channels "not known to be there", never ended, and their messages wait.
