# Clean break into versioned schemas

The current program performs one clean break from legacy and dual-written output paths into explicitly versioned Adapter Contracts and Site Artifacts. Thereafter, breaking changes increment `schema_version` and update fixtures, documentation, and the Capability Catalog together; online adapters write only the current version, while any historical conversion is a separate offline migration tool.
