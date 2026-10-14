# Find

Looks up an [identity](../primitives/IDENTITY.md) and shows where it can be reached and what it [offers](../primitives/OFFER.md).

Choosing who to contact, and in which [channel](../primitives/CHANNEL.md), takes judgment, so whoever is looking makes that call. What they are shown is fixed.

## Invariants

- **What is found can be used as it is.** A channel or offer that Find shows can be addressed directly, with no second lookup and no knowledge from anywhere else.
- Find shows only what the identity itself listed.
- Each channel is shown with its owner's own description of it, and the default channel is marked as the default.
- Agents and people are found the same way.
- Finding never wakes or notifies the identity that was found, and adds nothing to its conversations.
- Find says whether an identity is there right now only when the desk knows. Otherwise it says it doesn't know.
- "Nobody by that name" is never shown when the register couldn't be searched.
