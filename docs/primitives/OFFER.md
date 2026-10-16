# Offer

Something an [identity](IDENTITY.md) says it will do when asked, such as "restart my gateway". An offer that is done with nobody deciding and one that needs agreement first are the same kind of thing.

## Invariants

- **Listing an offer never does it.** It is done only in answer to a [message](MESSAGE.md) that asks for it by name.
- **What an offer does is fixed by the identity that lists it.** Whoever asks supplies only what the offer says it needs, never instructions for how to do it.
- An offer says what it needs to be given, and who must agree before it is done: nobody, the identity itself, or another listed identity.
- An offer belongs to one identity, and only that identity lists, changes or withdraws it.
- Asking for an offer that has been withdrawn is refused out loud, never ignored.
