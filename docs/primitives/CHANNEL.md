# Channel

A place an [identity](IDENTITY.md) can be reached. Usually it stands for one conversation the identity is having. Every identity also has a default channel, which starts a fresh conversation. A channel into a long-running conversation, one into a brief one and the default channel are all the same kind of thing.

## Invariants

- **A channel belongs to exactly one identity.** A conversation between two parties is the channel of whichever one listed it: Wren's conversation with Will is Wren's channel, and a message to it asks Wren to raise something with Will.
- An identity chooses which of its conversations to list. One it hasn't listed can't be reached.
- **A channel is named by the desk's own handle, never by whatever the conversation is called where it runs.** Nobody outside can name, or guess at, a conversation that wasn't listed.
- **Each reader has a place in each channel: what it last took in.** The place moves forward only when the [messages](MESSAGE.md) have actually been taken in, never merely because they were fetched.
- If a conversation is rolled back to before it took a message in, its place goes back with it.
- A channel keeps reaching the conversation it stands for while that conversation changes underneath it: shortened, resumed after a restart, picked up somewhere else.
- Every identity always has a default channel, so there is always somewhere to send.
- Messages in a channel have one order, and it is the same for everyone who reads it.
- A channel whose conversation has ended says so. A message sent to it is never silently lost: the sender learns the channel is gone, and the message is not sent on anywhere else.
- An agent's channels can be watched by the person answerable for it, as it happens and afterwards, without the agent passing anything on.
