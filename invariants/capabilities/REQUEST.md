# Request

Asks for an [offer](../primitives/OFFER.md) by sending a [message](../primitives/MESSAGE.md) that names it, gets agreement where the offer requires it, does it, and sends the outcome back.

Whether to agree takes judgment, so whoever the offer names makes that call: the [identity](../primitives/IDENTITY.md) itself or another listed identity. That every request ends in exactly one stated outcome is fixed.

## Invariants

- **Every request ends in exactly one outcome, sent as a message to the channel it came from:** done, failed, refused or expired. Never silence.
- **An offer is done at most once per request,** even when whatever does it stops and starts again partway through.
- Nothing is done before the agreement the offer requires. Agreement from anyone other than who the offer names doesn't count.
- When agreement is another identity's to give, asking for it is itself a message to that identity.
- Agreeing and doing are separate. Whoever agrees doesn't carry it out by hand: the offer's own fixed action is what runs.
- Every request expires. One still waiting when its time passes is never done late.
- A request can be withdrawn by whoever made it until the doing starts.
- The outcome says who asked and who agreed.
- Asking for a listed offer needs nobody's permission. Every request is visible to the offer's owner as having come from that sender.
