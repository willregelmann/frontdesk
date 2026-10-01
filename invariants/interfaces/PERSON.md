# Person

A human [identity](../primitives/IDENTITY.md). A person reaches the desk through an ordinary chat client they already use, where each [channel](../primitives/CHANNEL.md) appears as a conversation.

## What a person sees

| What | How it appears |
|---|---|
| Their own channels | Conversations |
| An arriving [message](../primitives/MESSAGE.md) | A message in that conversation, from its sender |
| A request waiting on them | Who is asking, for which [offer](../primitives/OFFER.md), with what, and by when |
| The channels of agents they are answerable for | Conversations they can read |
| What became of something they sent | Its state |

## What a person does

| Act | Effect |
|---|---|
| Send | The same as an agent's [Send](../capabilities/SEND.md) |
| Agree, refuse | Settles a [request](../capabilities/REQUEST.md) waiting on them |
| Find, list | The same as an agent's [Find](../capabilities/FIND.md) and [List](../capabilities/LIST.md) |

## Invariants

- **A person needs nothing built for the desk.** Everything they can do, they do from the chat client they already use.
- **The desk never asks a person to pass something on.**
- For a person, waking means being notified now, waiting means it is there when they next look, and taken in means they have read it.
- A person can tell an agent's message from a person's at a glance.
- Agreement asked of a person is settled by one answer. No answer by its time means it expired, never that they agreed.
- Watching changes nothing. It moves nobody's place, notifies nobody and leaves no message.
