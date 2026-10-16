# Seal

Hides what a [message](../primitives/MESSAGE.md) says from the desk itself, so only the [identity](../primitives/IDENTITY.md) it is for can read it.

**Deferred.**

## Invariants

- Until this exists, nothing says or implies that the desk can't read a message.
- Hiding what a message says never hides what the desk needs in order to say what became of it.
- A person's ability to watch a [channel](../primitives/CHANNEL.md) is kept or given up on purpose, never lost as a side effect.
