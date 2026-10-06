# Planning terms

A task is one result that can receive its own review and leave main usable.
A dependency means another result must exist before this task can be correct.
A DAG is a directed graph with no dependency cycle.
An antichain contains tasks with no dependency path between them.
MECE means mutually exclusive and collectively exhaustive within a stated scope.
A workstream owns one class of results; cross-stream dependencies remain explicit.
A gate is a condition that permits progress. It can depend on an external person or environment.
A lease is a reservation with an expiry time. It cannot stop an expired worker from writing.
Fencing means that the protected resource rejects a stale owner's write.
A receipt records a result and its source coordinates. It is not proof of untested behavior.

These documents use ASD-STE100 writing guidance. Full dictionary and formal compliance review are not complete.
