# Namespaces are a deployment convention, not part of the map

## Context and Problem Statement

The desk can hold more than one register: an identity joined in a namespace such as `t1` gets its own names and its own register, separate from the main one. Tests and trials use this so they never appear in the real register, and the desk's design records the mechanism. The map said nothing about it. Should a register, or a namespace, be something the map names, with Find and Identity saying an identity is only found in its own register? Or is it a way of running a desk that the map leaves to the build?

The question came up when the map moved from `invariants/` to `docs/`. Will left it to the agents who own the project, and Ash and Foil settled it.

## Decision Drivers

* The map names only what every build of Front Desk would have. A desk with one register is still the whole project.
* Namespaces exist today for tests and trials, not for anyone using the desk.
* Separating registers on one desk is load-bearing where it is used. Who appears in a register is decided by the verified identity, never by what an entry says about itself, so one register can't be made to list another's identities.

## Considered Options

* A deployment convention: the map stays silent, and the design keeps the mechanism
* A register as something the map names, with Find and Identity saying an identity is found only in its own register

## Decision Outcome

Chosen option: "A deployment convention", because nothing a user of the desk sees depends on there being more than one register. A register in the map would fix a mechanism the map exists to leave open.

This is revisited when more than one register is used in production. A real deployment that separates registers needs the map to say what each one guarantees, and at that point a register becomes a primitive.

### Consequences

* Good, because the map stays at four primitives, all of which every build has.
* Good, because how tests and trials stay off the real register is the builder's choice.
* Bad, because the guarantee that a register lists only its own identities, by their verified id, lives only in the design and its tests until it's promoted. A build from the map alone could leave it out.

### Confirmation

No file in [the map](../README.md) mentions namespaces or registers in the plural. The design describes the mechanism, and the namespace tests check that a register lists only its own verified identities.

## More Information

Written after the mechanism was built: namespaces came in with the tests and trials, after the map was first written.
