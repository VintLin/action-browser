# Use typed failure reasons as the control contract

Adapters report stable typed `reason_code` values in the Adapter Contract, and scheduler transitions and retry policy consume those values rather than parsing messages or copying opencli's numeric exit codes. A shared entrypoint maps the typed outcome to a small CLI exit-code set, while site implementations may add diagnostic prose but cannot invent control semantics in free text.
