# Evidence contracts and source audit

The eight downloaded AOSP files are pinned to Android 13/15 release tags, with URLs and hashes in `source-audit/manifest.json`. They are explanatory source evidence, not a claim of byte-identical source for the Google emulator provider APKs. Runtime fingerprints are recorded separately.

| Adapter | Stronger evidence examined | Missing obligation / disposition |
|---|---|---|
| Contacts | Complete RawContacts map rather than truncated digest; data/version triggers in ContactsDatabaseHelper around lines 1730–1765 (Android 15) | Query uses Data/display-name and aggregate Contacts views; provider incarnation and restoration contract not established. Strict UNKNOWN. |
| MediaStore | Version plus generation; complete projected rows and query values | DatabaseHelper increments generation inside beginTransaction (Android 15 lines 811–820); MediaProvider version combines schema and database UUID (around line 7039). This supports a candidate bracket under normal writes, but does not establish all query visibility, cursor, restore and deployed binary assumptions. Strict UNKNOWN pending that validation. |
| Call log | Full ID/content/LAST_MODIFIED rows, beyond maximum timestamp | Timestamp resolution and clock restoration do not supply non-repeating revisions. 4,000 native rapid edit/read pairs found no equal-tick collision; that negative result does not prove impossibility. Testing-only clock override is restricted to the provider package and was not impersonated. Strict UNKNOWN. |
| Files | Content reads plus paths; historical max mtime/count retained | Reads are useful for refresh/memoization; concurrent replacement, content edits and identity are not certified by metadata equality. Strict UNKNOWN. |
| SMS/calendar/settings | Actual query results | No complete revision/epoch contract established. Strict UNKNOWN. |
| Cooperative reference | Atomic rows, epoch and revision in a separate SQLite provider process | FRESH only under API-mediated writes and managed reset/restore. Out-of-band rollback preserving metadata is excluded. |

The richer stock evidence is logged by `stock_evidence`, but explicitly has `certified=false`. No before/after stamp equality enables strict stock reuse. This is a negative adapter result, not a silently weakened freshness promise. Stock reset/rollback coverage is not inferred from the cooperative reset/restore tests or from historical clock experiments.

The reference provider uses complete state snapshots, not a compact delta API. CHANGED means a witnessed answer difference; version/epoch changes alone can yield UNKNOWN. An ABA change with identical final answer can return FRESH at the new snapshot. No certificate extends to a later action.
