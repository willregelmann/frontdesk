# Message

Anything that passes through the desk. A question, an answer, a wake-up call, a request and its outcome are all messages. What differs is which [channel](CHANNEL.md) they are addressed to and what they ask for.

## Invariants

- **Every message says who sent it and which channel it came from.** That channel is where an answer goes.
- **An answer is a new message, never a return value.** Nothing is held open waiting for one, and the sender is never stuck until it comes.
- **The desk can always say what became of a message:** accepted, arrived, taken in, refused or expired. Accepted is never reported as arrived, and arrived is never reported as taken in.
- The sender chooses how a message arrives: it waits to be read, it wakes the receiver now, or it is held until a set time. A waiting message never wakes anyone. A waking message is never left sitting once the receiver is free to act.
- A message addressed to the sender's own channel is treated like any other.
- In the receiver's conversation a message appears as what it is: from that sender, through the desk. It never appears as if the receiver's own partner, or the receiver itself, had said it.
- A message that answers or follows another says which one.
- A message is never changed after it is sent. Anything that follows is another message.
- A message arrives in its channel once, however many times sending it was retried.
- A message can carry a time after which it must not arrive or be acted on. Past that time the desk says it expired.
- A held message can be withdrawn by its sender until the moment it arrives.
