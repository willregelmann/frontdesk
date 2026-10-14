# One kind of message: answers, wake-ups, requests and outcomes differ by channel and by what they ask for

## Context and Problem Statement

Parties reaching each other through the desk ask questions, answer them, wake someone up, ask for something to be done and hear how it went. Are these different kinds of thing, or one?

## Considered Options

* One kind of [message](../primitives/MESSAGE.md), differing by which [channel](../primitives/CHANNEL.md) it is addressed to and what it asks for

## Decision Outcome

Chosen option: "One kind of message". Reason: TODO. The intent states the idea, "everything between two parties goes through the desk as a message to a channel, and an answer is just another message back to the channel it came from", but not what it was chosen over.

### Consequences

* Good, because an answer, a wake-up call and an outcome need no machinery of their own: each is sent, received and accounted for like any message.
* Good, because nothing is held open waiting for an answer.

### Confirmation

[Message](../primitives/MESSAGE.md): "An answer is a new message, never a return value", and "A message addressed to the sender's own channel is treated like any other". [Request](../capabilities/REQUEST.md): every request ends in exactly one outcome, sent as a message.

## More Information

Written after the fact. The choice is in the first version of the map, written by Will.
