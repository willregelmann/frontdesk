# A channel belongs to exactly one identity

## Context and Problem Statement

A conversation between two parties could be something they share, or something one of them owns. When Wren and Will are talking, whose is that conversation as far as the desk is concerned, and what does a message sent to it mean?

## Considered Options

* A [channel](../primitives/CHANNEL.md) belongs to exactly one [identity](../primitives/IDENTITY.md): a conversation between two parties is the channel of whichever one listed it

## Decision Outcome

Chosen option: "A channel belongs to exactly one identity". Reason: TODO.

### Consequences

* Good, because a message to Wren's conversation with Will has one meaning: it asks Wren to raise something with Will.
* Good, because only the identity that owns a channel lists or withdraws it.
* Bad, because a conversation with more than two parties has no shape in the map yet.

### Confirmation

[Channel](../primitives/CHANNEL.md): "A channel belongs to exactly one identity", and "An identity chooses which of its conversations to list".

## More Information

Written after the fact. The choice is in the first version of the map, written by Will.
