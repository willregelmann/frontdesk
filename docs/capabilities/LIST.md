# List

Changes what the register says about an [identity](../primitives/IDENTITY.md): joining, listing or withdrawing its [channels](../primitives/CHANNEL.md) and [offers](../primitives/OFFER.md), and changing how it proves itself.

Which conversations are worth listing, and what to offer, takes judgment, so the identity makes that call. That the register never says more than is true is fixed.

## Invariants

- **The register is never ahead of the truth.** A channel is listed only for a conversation that exists, and it is withdrawn when that conversation ends.
- A channel is not withdrawn merely because whatever runs its conversation has stopped for a while.
- The default channel can't be withdrawn while its identity is listed.
- Listing the same thing twice leaves one listing.
- Changing how an identity proves itself takes the proof it has now.
- An identity can leave the register. Its name is never then given to someone else as if they were the same identity.
- A listing that couldn't be made says so. An identity is never left believing it can be reached when it can't.
