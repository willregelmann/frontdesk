# Send

Leaves a [message](../primitives/MESSAGE.md) for a [channel](../primitives/CHANNEL.md): one that waits to be read, one that wakes the receiver now, or one held until a set time. An answer and a wake-up call are sent the same way as anything else.

What to say, to whom and how urgently takes judgment, so the sender makes that call. That the message is recorded, attributed and accounted for is fixed.

## Invariants

- **Send comes back as soon as the desk has the message, and says only that.** It never implies the receiver has it.
- **Every attempt to send leaves a record the sender can look up,** including the ones that failed, with why.
- The channel a message came from is filled in by the desk from where the sender actually is. A sender can't claim to be sending from a channel that isn't its own.
- **Sending from a conversation that isn't listed lists it,** so the answer comes back to the conversation that asked.
- Sending to a listed channel needs nobody's permission. Every message that arrives is visible to the channel's owner as having come from that sender.
- Nothing limits how often, how far or when messages are sent. The record of every attempt is what shows misuse.
- A message to a channel that has ended is refused, and the sender is told. Choosing another channel is up to the sender.
- A message carries the sender's place in the channel it is answering, so the receiver can tell what the sender had and hadn't seen when it wrote.
- A held message arrives at its time whether or not its sender is still there.
- A held message that comes due while the desk couldn't deliver it arrives as soon as it can, and says it is late.
