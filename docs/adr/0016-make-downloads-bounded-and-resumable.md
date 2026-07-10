# Make downloads bounded and resumable

Download and export capabilities require an explicit output root, atomic temporary-file replacement, a per-item Download Manifest, size and content-type checks, and total-byte limits. Reruns skip only verified files and resume failed items; remote metadata success and local media failure are reported separately so partial file failures never discard valid extracted data.
