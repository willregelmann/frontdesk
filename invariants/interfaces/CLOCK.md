# Clock

Time. It is what makes a held [message](../primitives/MESSAGE.md) arrive and an unanswered one expire, with nobody acting.

## What time brings

| Moment | What happens |
|---|---|
| A held message's time comes | It arrives, as its sender chose ([Send](../capabilities/SEND.md)) |
| A message's limit passes | It expires and is not brought in ([Receive](../capabilities/RECEIVE.md)) |
| A request's limit passes | Its outcome, expired, is sent back ([Request](../capabilities/REQUEST.md)) |
| A due time passed while the desk or a host was down | It happens as soon as it can, and says it is late |

## Invariants

- **Nothing that is due depends on anyone being there to notice.**
- A held message never arrives early.
- Late is said, never hidden. Anything that happens after its time says how late.
- A limit beats lateness. Something past its limit is not done late: it expires.
- The time a message is held until is fixed when it is sent. A restart, or its sender leaving, doesn't move it.
- A held message whose [channel](../primitives/CHANNEL.md) has ended by its time is refused then, and the record says so.
