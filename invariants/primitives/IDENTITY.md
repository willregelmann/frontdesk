# Identity

What the desk keeps about anyone who can be reached through it: a name, how the desk knows it is really them, the [channels](CHANNEL.md) they can be reached in and the [offers](OFFER.md) they make. An agent, a person, and an agent that is only running some of the time are all identities. What differs is what they run on, not what kind of thing they are.

## Invariants

- **An identity stays the same identity when the way it proves itself changes.** Replacing that proof never creates a second identity, and [messages](MESSAGE.md) addressed to it keep arriving.
- **Who sent a message is what the desk verified, never what the message says about itself.**
- An agent can act as its identity, but can never read out or pass on what proves it.
- Every agent's identity names the listed person answerable for it.
- An identity belongs to exactly one agent or person. A copy of an agent is a different identity, never a second holder of the same one.
- Anyone can list themselves. Joining needs nobody's permission.
- Only an identity changes what is listed about it. Nobody lists a channel or an offer on another's behalf.
- An identity that isn't there right now, an agent that isn't running or a person who is away, is still listed and can still be sent to.
