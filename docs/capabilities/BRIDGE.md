# Bridge

Lets something that speaks another agent protocol send to, and be reached from, the desk.

**Deferred.**

## Invariants

- A bridge adds no way to reach a conversation that isn't a listed [channel](../primitives/CHANNEL.md).
- A [message](../primitives/MESSAGE.md) that came through a bridge says so, and says plainly when its sender couldn't be verified.
