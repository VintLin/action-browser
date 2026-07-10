# Use risk-tiered real-browser regression

Every Delivery Batch runs the complete deterministic suite, and changed sites smoke all affected capabilities. Shared-runtime changes run lifecycle tests plus a Canary Matrix spanning public HTTP, authenticated API, DOM, UI, temporary tabs, downloads, and User Gates rather than every capability; monthly Maintenance Cycles run at least one canary per Supported Website, while only major runtime changes trigger full real-browser regression.
