# Merge bases

The pristine upstream PKGBUILD each vendored package was copied from, as
fetched, before any of our edits.

They exist so `scripts/track_upstreams.py` can do a real three-way merge.
Without a base, "merging" an upstream change into our copy is just an
overwrite: it silently reverts the local edits five of these packages carry
(`arch=` widened to aarch64, wluma's broken man-page step removed) while
reporting success. Verified — that is what the first version of the script
did before this directory existed.

Nothing builds from these files. `track_upstreams.py --apply` refreshes one
only when it has merged that package's change into `packages/<name>/PKGBUILD`,
so base and vendored copy always describe the same upstream revision.
