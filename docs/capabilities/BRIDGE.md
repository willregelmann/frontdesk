# Bridge

Lets something outside the desk send to, and be reached from, the desk: another agent protocol, a chat service, email, a ticket tracker. Each kind of outside system has its own bridge; what a bridge must keep is the same for all of them.

**Deferred.**

## Invariants

- A bridge adds no way to reach a conversation that isn't a listed [channel](../primitives/CHANNEL.md).
- A [message](../primitives/MESSAGE.md) that came through a bridge says so, and says plainly when its sender couldn't be verified.
- **An outside account speaks as an [identity](../primitives/IDENTITY.md) only when that identity has listed the account itself, and the outside system has authenticated it.** Anything else arrives shown as unverified, under the account's outside name. A bridge never decides who an outside account is, and never sends as someone the desk hasn't verified.
- A message a bridge carries out says which identity sent it, as plainly as the outside system allows.
- **An outside thread reaches the desk only as a channel that one identity listed.** A thread several parties share, such as a ticket or a mailing list, is each identity's own channel for its part in it, never a channel that belongs to the thread.
- What the outside system calls a thread never names the channel. An outside address that matches no listed channel reaches the identity's default channel or is refused, never an unlisted conversation.
- Where the outside system can't do what a message asks, such as waking a reader now or reporting that it was read, the message's state says what is not known. A bridge never pretends.
