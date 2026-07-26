---
name: loopx-material
description: Operate an explicitly activated LoopX Material Lifecycle for a connected project. Use for material-store inventory, lossless migration, candidate/archive transitions, exact-read-backed ranking, ranked-entry rebuilds, bounded Explore intake, owner-gated apply, rollback, and audit. Do not use for ordinary one-off reading or research when the project has not activated Material Lifecycle.
---

# LoopX Material

Use this skill for the lifecycle and authority of a project's durable material
store. Source discovery, domain-specific scoring, and note writing may be
provided by project skills; this skill owns the generic lossless lifecycle.

The skill is installed globally with LoopX so every worker receives one
versioned workflow. It is active only for a connected project's explicit
goal-scoped Material Lifecycle work. Do not copy this skill into each project
or infer activation merely because a material file exists.

## Activation Gate

Before changing a material store:

1. Resolve the current project, `goal_id`, registered agent, and active todo
   through `loopx start-goal --guided`, `loopx status`, or `loopx diagnose`.
2. Confirm the selected todo explicitly targets `material_lifecycle`, or that
   the goal authority declares an active Material Lifecycle profile and its
   source store. A catalog entry or globally installed skill is not activation.
3. Confirm the goal boundary covers the exact private adapter and authority
   paths. Public LoopX contracts never grant access to private source content.
4. Run `loopx material-lifecycle architecture --format json` and preserve its
   default-off, owner-gated, provider-neutral boundaries.

If activation or authority is missing, stop before source mutation. Create a
bounded setup todo or owner gate; do not silently install project-local copies,
invent a store, or treat chat history as authority.

## Ownership Boundary

Keep these responsibilities separate:

- **Project source adapter**: locates and reads the project's private source
  files, database, documents, or provider.
- **Research/reader skill**: recalls candidates, performs exact reads, and
  produces source-quality and domain-value evidence.
- **Decision Context**: supplies revision-bound objectives, changed facts,
  conflicts, and accepted decisions.
- **Material Lifecycle**: owns inventory, migration, lifecycle transitions,
  ranked-entry rebuild, rerank proposals, apply receipts, and rollback.
- **Content or notes workflow**: consumes selected material and produces an
  artifact; it does not rewrite candidate/archive/ranking truth by itself.

## Workflow

### 1. Snapshot And Inventory

Read the source authority before proposing structural change.

- Record source revision, byte/content digest, lifecycle counts, parse errors,
  stable material references, and a verified backup.
- Keep raw content, private paths, URLs, provider payloads, and credentials out
  of public packets and commits.
- Preserve the original source until a verified cutover and rollback rehearsal
  have both succeeded.

No migration, rebuild, or rerank may begin from an unverified partial parse.

### 2. Normalize Lifecycle

Use stable material references across:

```text
candidate -> active -> archived
                 \-> carryover
archived -> active
```

Every transition needs a revisioned evidence or decision reference. Archiving
must preserve the original source reference and an archive reference. Reading,
summarizing, or publishing a note does not implicitly archive a material.

### 3. Promote Exact-Read Evidence

Recall is advisory. Before a material affects ranking or lifecycle:

1. retrieve the candidate through the configured provider or local search;
2. exact-read the authoritative source;
3. record source revision and read scope;
4. reject stale, conflicting, unreadable, or only-secondary claims;
5. pass only promoted evidence into Decision Context or ranking.

Do not start Explore merely because the current list feels incomplete. Explore
begins only from a named evidence gap, bounded query plan, budget, and stop
condition.

### 4. Rebuild Ranked Entries

A ranked entry must represent one independently sortable reading or action
unit, not a display bucket.

- Default to at most three primary materials per ranked entry.
- When an entry exceeds the limit, create deterministic child entries and rank
  them independently.
- Do not hide overflow in an unranked supporting index.
- Preserve exact membership: every selected material appears exactly once
  across the ranked set.
- Preserve stable material references and canonical source records.
- Keep an explicit ranked backlog beyond a visible Top-N.

Splitting is semantic, not mechanical. Group materials only when they jointly
support one decision or learning outcome; separate materials whose value,
urgency, reader action, or evidence maturity differs.

### 5. Propose A Bounded Rerank

Rerank from revision-bound Decision Context evidence.

- Protect pinned entries and the project's declared stable prefix.
- Limit moved entries and rank displacement unless the owner explicitly
  approves a structural rebuild.
- Distinguish a rank move from lifecycle change and from new candidate intake.
- Emit a no-change proposal when evidence does not justify movement.
- Keep proposal and apply receipt separate.

### 6. Apply With A Lossless Gate

Preview first. Apply only when all are true:

- source and backup digests still match the inventory;
- parse errors are zero or explicitly owner-approved;
- expected source/canonical counts match;
- ranked coverage and unique membership are exact;
- protected entries remain valid;
- compare-and-swap revision matches;
- rollback has been rehearsed;
- the owner gate authorizes this exact plan.

After apply, read the destination back and write an audited receipt. On any
mismatch, restore the previous authority and record the blocker. Never report
"migration complete" from a preparation plan alone.

## Project Adapter Contract

A project-specific skill or `AGENTS.md` may define:

- source locations and private provider setup;
- topic taxonomy and domain scoring;
- reading tools and source-specific fallbacks;
- user-specific priorities;
- note/archive destinations and public/private redaction;
- concrete backup and restore commands.

It should reference this skill instead of duplicating generic migration,
ranking, rebuild, apply, or rollback rules. Project rules may tighten these
invariants but must not weaken them.

## Completion Evidence

A complete material operation reports:

- source and destination revisions;
- backup and source-digest verification;
- parsed and canonical counts;
- lifecycle-count delta;
- ranked-entry count and maximum primary-member count;
- exact coverage and duplicate count;
- promoted/rejected exact-read evidence;
- proposal and apply receipt references;
- rollback result;
- next bounded action or explicit no-change.

## Stop Conditions

Stop without mutating the source when:

- the project or goal is ambiguous;
- Material Lifecycle is not explicitly active for the selected goal;
- source authority, backup, revision, or stable ids cannot be verified;
- exact-read evidence conflicts with the proposed change;
- overflow would be hidden rather than independently ranked;
- a migration would lose bytes, records, references, or recoverability;
- the required owner gate, write scope, or rollback path is absent;
- public output would expose private material or credentials.
