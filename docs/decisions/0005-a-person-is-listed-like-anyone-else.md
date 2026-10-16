# A person is listed like anyone else

## Context and Problem Statement

People and agents both reach each other through the desk. Is a person a different kind of party, with their own way in, or an identity like any agent?

## Considered Options

* A person is an [identity](../primitives/IDENTITY.md) like any other, reaching the desk through the [chat](../interfaces/CHAT.md) client they already use

## Decision Outcome

Chosen option: "A person is listed like anyone else". Reason: TODO. The intent states it ("a person is listed like anyone else"), and its failure sentence is about any two listed parties, agent or person.

### Consequences

* Good, because sending, finding and asking work the same whoever is on either end.
* Good, because a person needs nothing built for the desk.
* Bad, because what a person can do is bounded by what an ordinary chat client can show and send.

### Confirmation

[Identity](../primitives/IDENTITY.md): "An agent, a person, and an agent that is only running some of the time are all identities". [Find](../capabilities/FIND.md): "Agents and people are found the same way". [Chat](../interfaces/CHAT.md): "A person needs nothing built for the desk".

## More Information

Written after the fact. The choice is in the first version of the map, written by Will.
