# What an offer does is fixed by the identity that lists it

## Context and Problem Statement

An identity can say it will do something when asked, such as "restart my gateway". When someone asks, how much do they decide about what is done?

## Considered Options

* What an [offer](../primitives/OFFER.md) does is fixed by the identity that lists it. Whoever asks supplies only what the offer says it needs

## Decision Outcome

Chosen option: "Fixed by the identity that lists it". Reason: TODO.

### Consequences

* Good, because asking for an offer needs nobody's permission: the worst a request can do is run what the owner already chose to offer.
* Good, because agreeing and doing stay separate. Whoever agrees never carries the offer out by hand.
* Bad, because anything the offer's owner didn't foresee needs a new offer, not a parameter.

### Confirmation

[Offer](../primitives/OFFER.md): "Listing an offer never does it", and "What an offer does is fixed by the identity that lists it". [Request](../capabilities/REQUEST.md): "Agreeing and doing are separate".

## More Information

Written after the fact. The choice is in the first version of the map, written by Will.
