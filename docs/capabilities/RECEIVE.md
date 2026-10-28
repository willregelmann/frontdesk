# Receive

Brings a [message](../primitives/MESSAGE.md) into the conversation its [channel](../primitives/CHANNEL.md) stands for, in the way the sender chose, and moves the reader's place.

What to do about a message, including nothing at all, takes judgment, so the receiver makes that call. That the message is shown, when it is shown and what it is marked as is fixed.

## Invariants

- **A waking message starts the receiver acting with nobody prompting it.**
- **A waiting message is shown the next time its conversation is active, without being asked for.** It is never left to be discovered.
- A message never interrupts. If the receiver is in the middle of something, the message is taken up when that finishes.
- Messages that arrived while the receiver was busy or away are shown together, in the channel's order.
- Receiving only adds to a conversation. It never changes anything already in it.
- Taking a message in doesn't oblige an answer. Staying silent is recorded as taken in, never as a failure.
- A receiver that stops partway takes the same messages in again. None is skipped.
- A waking message for a receiver that isn't there wakes it when it next is, and says it is late.
- A message to a default channel waits when nothing is able to start a conversation for it, and its state says it is waiting. It is never reported as arrived.
- A message past its time is not brought in.
