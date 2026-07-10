# Use an atomic capability lifecycle

Each Capability Record follows `discovered → specified → implemented → verified | verified_empty`, with only `waiting_user`, `blocked`, `excluded`, and `deprecated` as explicit side states. A single capability cannot be partial: missing fields, tests, contracts, or smoke evidence keep it unfinished, while partial completion is calculated only for aggregate site and wave reporting.
