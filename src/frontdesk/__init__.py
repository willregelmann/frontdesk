"""Front Desk: a register of agents and people, and one way to reach any of them in the
conversation they are actually in. The map of what must always hold is in ``invariants/``;
how it is laid onto a Matrix homeserver is in ``DESIGN.md``."""

from frontdesk.desk import Desk, DeskError, Host
from frontdesk.wire import Arrival, Listing, Receipt, Trace

__all__ = ["Arrival", "Desk", "DeskError", "Host", "Listing", "Receipt", "Trace"]
