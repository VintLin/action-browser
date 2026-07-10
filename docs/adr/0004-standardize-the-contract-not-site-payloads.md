# Standardize the adapter contract, not site payloads

Every adapter run will expose one common Adapter Contract for summary, progress, and artifact discovery, while posts, videos, products, jobs, and other Site Artifacts retain domain-specific schemas under the same output root. Migration removes dual scheduler paths and compatibility branches rather than forcing unrelated website data into a universal payload model.
