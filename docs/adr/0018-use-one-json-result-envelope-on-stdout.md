# Use one JSON result envelope on stdout

After the clean break, every command writes exactly one versioned JSON Result Envelope to stdout containing capability status, Adapter Contract location, Site Artifact references, and typed Failure Reason; logs go only to stderr. Human-readable Markdown is an artifact view, and action-browser does not add opencli-style table, YAML, CSV, or mixed-log output modes.
