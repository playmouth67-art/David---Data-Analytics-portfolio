# Business Rules Matrix

## Project context

These files appear to contain email campaign / recipient interaction
records. Each row represents an email recipient associated with a
specific send event.

The available fields include:

- email
- Badmail
- Baja
- Fecha envio
- Fecha open
- Opens
- Opens virales
- Fecha click
- Clicks
- Clicks virales
- Links
- IPs
- Navegadores
- Plataformas

The project objective is to understand the data structure, identify
valid and invalid records, distinguish true data-quality problems from
legitimate business scenarios, and document all decisions made during
the investigation.

This document defines the business and technical rules that will be
applied by the ETL process after structural validation and staging.

---

# 1. Rule classification

The ETL uses four operational classifications:

| Classification | Meaning | ETL behavior |
|---|---|---|
| VALID | Record is consistent with the currently known business rules | Load normally |
| WARNING | Record presents an anomaly or unusual combination that may be legitimate | Load and register in `errores` |
| ERROR | Record violates an objective technical or business rule | Reject from final fact table and register in `errores` |
| UNKNOWN | Current source data is insufficient to determine whether the condition is valid or invalid | Do not modify the record; register for audit |

`WARNING` does not mean that the record is invalid.

A warning indicates that the record should remain available for analysis
while being explicitly documented for subsequent investigation or
business confirmation.

---

# 2. Core principles

## Rule 1 — Missing values are not automatically errors

An empty value or `-` may represent a legitimate state.

Examples:

- No open -> `Fecha open` may legitimately be `-`
- No click -> `Fecha click` may legitimately be `-`
- No click -> `Links` may legitimately be `-`
- No interaction -> IP/browser/platform may legitimately be `-`

Therefore missingness must be interpreted according to the semantic
meaning of each field.

The ETL must not convert a missing value into an error solely because
the value is empty or represented by `-`.

---

## Rule 2 — Preserve source evidence

The staging layer must preserve the original semantic representation of
the source data before business transformations are applied.

In particular:

- `-` must not automatically be interpreted as `0`
- `-` must not automatically be interpreted as `NULL`
- source values must remain traceable to the original file
- `numero_fila` must identify the original source row

Transformations and type conversions occur after structural validation
and staging.

---

## Rule 3 — Baja does not necessarily invalidate historical interaction

`Baja = SI` indicates an unsubscribe state.

An unsubscribe does not necessarily mean that all interaction fields must
be zero.

A recipient may:

- receive an email,
- open it,
- unsubscribe,
- later return to the email,
- click a link.

Therefore:

`Baja = SI + engagement`

is NOT automatically classified as an error.

It must be investigated in relation to timestamps when possible.

---

## Rule 4 — Badmail requires contextual interpretation

`Badmail = HARD` appears to represent a hard email delivery failure.

A record with `Badmail` populated and engagement should be investigated
because a hard delivery failure would normally be difficult to reconcile
with subsequent engagement.

However, this condition must initially be treated as a warning rather
than automatically deleting or correcting the record.

---

## Rule 5 — Do not modify ambiguous historical data

When the available information is insufficient to determine the correct
interpretation of a record, the ETL must not invent a correction.

The preferred behavior is:

1. preserve the original value;
2. classify the condition as `WARNING` or `UNKNOWN`;
3. register the condition in `errores`;
4. allow the record to continue through the pipeline unless the
   condition represents an objective `ERROR`.

---

# 3. Engagement consistency rules

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-001 | Opens > 0 AND Fecha open missing | Interaction count indicates an open but no open timestamp exists | ERROR | Reject record + audit |
| BR-002 | Opens = 0 AND Fecha open present | Timestamp indicates an open despite zero recorded opens | WARNING | Load + audit |
| BR-003 | Clicks > 0 AND Fecha click missing | Interaction count indicates a click but no click timestamp exists | ERROR | Reject record + audit |
| BR-004 | Clicks = 0 AND Fecha click present | Timestamp indicates a click despite zero recorded clicks | WARNING | Load + audit |
| BR-005 | Clicks > 0 AND Opens = 0 | Possible real-world scenario; click may have been recorded without an open event | WARNING | Load + audit |
| BR-006 | Fecha click < Fecha open | Click appears before open | WARNING | Load + audit |
| BR-007 | Links populated AND Clicks = 0 | Depends on the semantic meaning of `Links` | WARNING | Load + audit |
| BR-008 | Clicks > 0 AND Links missing | Click exists without associated link information | WARNING | Load + audit |
| BR-009 | Opens virales > Opens | Potentially inconsistent if viral opens are a subset of total opens | WARNING | Load + audit |
| BR-010 | Clicks virales > Clicks | Potentially inconsistent if viral clicks are a subset of total clicks | WARNING | Load + audit |

### BR-009 / BR-010 business assumption

The current information does not definitively establish that
`Opens virales` and `Clicks virales` are mathematical subsets of
`Opens` and `Clicks`.

Therefore these rules remain `WARNING` until the business definition is
confirmed.

If the business confirms that viral metrics are strict subsets, these
rules may be promoted to `ERROR`.

---

# 4. Delivery / unsubscribe rules

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-011 | Badmail populated AND engagement exists | Potential contradiction between delivery status and interaction | WARNING | Load + audit |
| BR-012 | Baja = SI AND engagement exists | Can represent legitimate historical interaction | VALID | Load normally |
| BR-013 | Baja = SI AND click exists | Possible historical interaction | VALID | Load normally |
| BR-014 | Baja = SI AND open exists | Possible historical interaction | VALID | Load normally |
| BR-015 | Baja = SI AND click timestamp occurs after Baja | Cannot be proven because no unsubscribe timestamp is available | UNKNOWN | Preserve + audit |
| BR-016 | Baja = SI AND open timestamp occurs after Baja | Cannot be proven because no unsubscribe timestamp is available | UNKNOWN | Preserve + audit |

### Important limitation

The current source files do not appear to contain an explicit timestamp
for the `Baja` event.

Therefore temporal rules involving the exact moment of unsubscribe cannot
currently be proven.

The ETL must not infer an unsubscribe timestamp from another field.

---

# 5. Technical metadata rules

Technical metadata such as IP, browser and platform may depend on the
implementation of the tracking system.

Their absence does not automatically invalidate an interaction record.

These conditions are therefore treated primarily as profiling and audit
signals rather than hard validation failures.

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-017 | IP present but no open | Could be valid depending on tracking implementation | WARNING | Load + audit |
| BR-018 | Browser present but no open | Could be valid depending on tracking implementation | WARNING | Load + audit |
| BR-019 | Platform present but no open | Could be valid depending on tracking implementation | WARNING | Load + audit |
| BR-020 | IP/browser/platform all missing while engagement exists | Potentially inconsistent metadata | WARNING | Load + audit |
| BR-021 | Open exists but IP missing | Not necessarily an error | WARNING | Load + audit |
| BR-022 | Click exists but IP missing | Not necessarily an error | WARNING | Load + audit |

These rules must not cause automatic record rejection unless a future
business definition explicitly establishes the corresponding metadata
as mandatory.

---

# 6. Date rules

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-023 | Invalid date format | Data-quality/type error | ERROR | Reject record + audit |
| BR-024 | Fecha open < Fecha envio | Interaction appears before send | WARNING | Load + audit |
| BR-025 | Fecha click < Fecha envio | Interaction appears before send | WARNING | Load + audit |
| BR-026 | Fecha click < Fecha open | Click appears before open | WARNING | Load + audit |
| BR-027 | Fecha open = Fecha envio | Possible valid scenario | VALID | Load normally |
| BR-028 | Fecha click = Fecha open | Possible valid scenario | VALID | Load normally |

### Date interpretation limitation

The source files contain records where open/click timestamps appear before
`Fecha envio`.

These records must NOT automatically be corrected or deleted.

Possible explanations include:

- timezone differences;
- source-system semantics;
- event recording behavior;
- delayed or reconstructed source data;
- meaning of `Fecha envio` different from the assumed send timestamp.

Until the business meaning is confirmed, these records remain warnings.

---

# 7. Duplicate rules

Duplicate detection must distinguish between:

- exact duplicates;
- repeated recipients;
- repeated recipient + send events;
- records containing different interaction states.

A repeated email is not automatically a duplicate.

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-029 | Same email appears multiple times | Could represent different send events | WARNING | Load + audit |
| BR-030 | Same email + Fecha envio appears multiple times | Strong duplicate indicator | WARNING | Apply ranking + audit |
| BR-031 | Complete records are identical | Exact duplicate candidate | WARNING | Deduplicate + audit |
| BR-032 | Same email has different interaction data | Could represent different states or conflicting records | WARNING | Apply business ranking + audit |

---

## Duplicate resolution strategy

For records sharing the same:

`email + fecha_envio`

the ETL must not perform a blind `DELETE`.

Instead, candidate records are ranked after their fields have been
validated and typed.

The ranking should prioritize the record containing the most complete
and meaningful interaction information.

Potential ranking criteria include:

1. valid record over invalid record;
2. record without structural/type errors;
3. greater valid engagement;
4. greater `Opens`;
5. greater `Clicks`;
6. greater availability of interaction metadata;
7. deterministic tie-breaker using source file and `numero_fila`.

The exact ranking must be deterministic.

The selected record is retained.

Non-selected records are documented as duplicate/deduplication events in
`errores` or the corresponding audit mechanism.

No source file is modified as part of deduplication.

---

# 8. Cross-file rules

Records must be compared across files without assuming that an email
appearing in multiple files represents a duplicate.

Different files may correspond to different campaigns or send events.

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-033 | Same email appears in two files | Not automatically duplicate | WARNING | Load + audit |
| BR-034 | Same email + same send timestamp appears in two files | Possible campaign/file overlap | WARNING | Apply duplicate analysis |
| BR-035 | Same email appears in files with different send timestamps | Potentially legitimate repeated recipient | VALID | Load normally |
| BR-036 | Same email + same send timestamp + conflicting interaction data | Important cross-file anomaly | WARNING | Apply ranking + audit |

---

# 9. Technical / structural validation rules

These validations establish whether a source record can be safely
interpreted before applying business rules.

| ID | Condition | Interpretation | Severity | ETL Action |
|---|---|---|---|---|
| BR-037 | Number of columns != 15 | Invalid source file structure | ERROR | Reject file |
| BR-038 | Required header missing or incorrect | Invalid source file structure | ERROR | Reject file |
| BR-039 | File is empty | Invalid input file | ERROR | Reject file |
| BR-040 | Email missing | Required business identifier unavailable | ERROR | Reject record |
| BR-041 | Email has invalid format | Invalid business identifier | ERROR | Reject record |
| BR-042 | Numeric field contains invalid numeric value | Invalid data type | ERROR | Reject record |
| BR-043 | Date field contains invalid date value | Invalid data type | ERROR | Reject record |
| BR-044 | Exact duplicate row exists | Duplicate source record | WARNING | Deduplicate + audit |
| BR-045 | Same email + Fecha envio appears more than once | Potential duplicate/business collision | WARNING | Apply ranking + audit |

---

# 10. Required field interpretation

The following fields are considered business-critical:

- `email`
- `Fecha envio`

If `email` is missing, the record cannot be reliably associated with a
recipient and therefore cannot enter the final fact table.

If `Fecha envio` is missing or invalid, the record cannot be reliably
associated with a send event.

These conditions are therefore classified as `ERROR`.

---

# 11. Numeric field validation

The following fields are expected to represent numeric measurements:

- Opens
- Opens virales
- Clicks
- Clicks virales
- Links

The ETL must distinguish between:

- valid numeric values;
- missing values represented by `-`;
- empty values;
- invalid non-numeric values.

A missing value is not automatically an error.

An explicitly malformed value that cannot be interpreted as the expected
numeric type is an `ERROR`.

Examples:

```text
"3"       -> valid
"0"       -> valid
"-"       -> missing/source state
""        -> missing/source state
"abc"     -> ERROR
"3.5"     -> depends on business definition