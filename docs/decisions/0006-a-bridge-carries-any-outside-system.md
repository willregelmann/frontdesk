# A bridge carries any outside system, not only other agent protocols

## Context and Problem Statement

Bridge was written for agents that speak another protocol. Will asked (Google Chat, 2026-10-15) whether Front Desk could support arbitrary channel types, such as email or Jira tickets, and agreed with Ash's answer that it could, through bridges, with Google Chat (frontdesk#30) as the first and email as the test that the bridge is generic. Does that need a new primitive, or does Bridge cover it?

## Decision Drivers

* Every channel belongs to exactly one identity (0003). A ticket or a mailing list is shared, so it can't be a channel as it stands.
* Who sent a message is what the desk verified. An email's From line proves nothing; mail counts as authenticated only when it carries a DKIM signature aligned with its From address, not any signature at all.
* An identity's listing is whatever it writes in its own register entry. The desk guards who writes, not what is written, so a listing alone can claim anyone's account.
* Only an identity changes what is listed about it (IDENTITY). So a bridge can't map an outside account to an identity, and can't create identities for outside users who never joined.
* A bridge must not become a way into a conversation the agent didn't list: that is the line that keeps outside text from reaching any conversation it likes.

## Considered Options

* Widen Bridge to any outside system, keeping the four primitives
* A new primitive for an outside channel type
* Leave outside systems to each host

## Decision Outcome

Chosen option: "Widen Bridge to any outside system", because the four primitives already hold for email and tickets once a shared thread is read as each identity's own channel for its part in it, and an unverifiable sender is shown as unverified rather than trusted. A new primitive would give shared channels an owner the map refuses them. Leaving it to hosts would let each host draw the injection line differently.

Bridge stays deferred: this records its scope, not that it is built.

### Consequences

* Good, because Google Chat, email and a ticket tracker are one capability with one set of invariants, and the first bridge built is the test of the next.
* Good, because the line that outside text reaches only listed channels holds for every outside system at once.
* Good, because an outside account becomes an identity the same way anything else about an identity does: that identity lists it. Will lists his Google account once, from his own identity, and proves it once from inside Google Chat, for instance by answering a code the bridge sends to that account. After that the bridge checks only the outside system's authentication of each sender.
* Bad, because addressing inside a thread several parties share (a group chat space, a mailing list) stays open, as 0003 left a conversation of more than two parties. Until the map gives it a shape, a bridge refuses or holds a post in a shared thread rather than guessing who it is for, so the first bridge is for one-to-one threads.
* Bad, because an outside system that gives no read state (Google Chat gives an app none) can never report taken in for a person reached through it. That the bridge posted a message is not that the person read it.
* Bad, because a ticket assignment arrives as a message, not as a [request](../capabilities/REQUEST.md) with an outcome owed. Reading an assignment as a request is a larger change to what a request is, and is left until a real use asks for it.

### Confirmation

Each bridge's tests include a message from an unverifiable sender, shown as unverified; an account that matches an identity's listed account but arrives unauthenticated, also shown as unverified; an account listed but never proven from inside the outside system, also shown as unverified; a second identity listing an account another identity has already proven, which gets nothing; and an outside thread that matches no listed channel, which never reaches an unlisted conversation.
