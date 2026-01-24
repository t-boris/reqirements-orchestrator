# Phase 32: Product Invariants - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<vision>
## How This Should Work

Invariants should work like physics — not rules humans follow, but laws the system enforces. Think rockets: checklists are great, but bolts that physically prevent the wrong part from fitting are better.

### Four Layers of Protection

**Layer 0: The contract is a type, not a comment**
- Invariants become named exceptions: `InvariantViolation`, `ManagedSectionMissing`, `PreflightRequired`
- Write APIs accept only typed inputs that guarantee checks passed
- You can't accidentally bypass because you can't construct the required types without proof

**Layer 1: Architecture boundaries (devs naturally do the right thing)**
- Choke points: one door, one key
- `jira_gateway.py` is the ONLY module that calls Jira create/update
- `slack_gateway.py` is the ONLY module that posts/edits messages
- `registry_service.py` is the ONLY module that commits decisions/workitems
- Everything else produces intents and plans, not side-effects
- Graph nodes return `ActionPlan` objects, only `dispatch()` executes them

**Layer 2: Type-safe commands with required tokens**
```python
# You cannot construct JiraUpdatePlan without PreflightToken
# You cannot construct ManagedSectionPatch without parsing the section
plan = JiraUpdatePlan(
    issue_key=...,
    patch=ManagedSectionPatch(...),
    preflight=PreflightToken(...)
)
jira_executor.execute(plan)
```

**Layer 3: CI gates (tests that prove invariants hold)**
- Forbidden direct imports: no module imports `atlassian` except gateway
- Property tests: random descriptions without managed section → must fail
- Preflight enforcement: attempt plan without token → must fail
- Slack failure tolerance: simulate failure → registry commits, Jira proceeds

**Layer 4: Runtime guardrails**
- Structured logs: `"invariant violated: MANAGED_SECTION_ONLY"`
- Operator messages: `"blocked to prevent overwrite"`
- Metrics: preflight conflicts, managed section missing, slack failures, retry success

### End-to-End Example

User clicks "Approve decision":
1. Commit decision to registry (truth) ✓
2. Build Jira projection plan
   - Parse managed section ✓
   - Acquire preflight token ✓
3. Execute Jira plan ✓ (or conflict prompts user)
4. Try updating canonical Slack message
   - If fails → log + retry queue
   - DO NOT roll back decision ✓

That is "Slack is UI, not truth" implemented as architecture.

</vision>

<essential>
## What Must Be Nailed

All layers are equally critical — they reinforce each other:

- **Types**: Make the wrong path hard to even attempt
- **Boundaries**: Make the right path the only obvious path
- **CI**: Make the wrong path impossible to ship
- **Runtime**: Make failures survivable and visible

**Summary rule of thumb:**
> Boundaries make the right path easy.
> Types make the wrong path hard.
> CI makes the wrong path impossible to ship.
> Runtime makes failures survivable.

</essential>

<specifics>
## Specific Ideas

### Escape Hatch Protocol

Default: hard fail. Emergency: allowed only with role + reason + TTL + audit + visibility.

**Why escape hatch exists:**
- Not for convenience — for resilience
- Production emergencies happen
- Full block makes system brittle

**Escape hatch UX (must feel like pulling a fire alarm):**

1. **Default — hard block with no easy bypass:**
```
⛔ Operation blocked (Invariant: PRECHECK_REQUIRED)

This action attempted to write to Jira without:
- PreflightToken (conflict prevention)
- ManagedSectionPatch (safe projection)

This is blocked to prevent data corruption.

[Show details] [Request override]
```

2. **Override requires explicit protocol:**
   - Role: only admin/owner/ops-role
   - Reason: required text ("prod incident", "jira down", etc.)
   - TTL: expires in 10 minutes or single action
   - Double confirm: "Are you sure?"

3. **Technical form — OverrideToken:**
```python
OverrideToken {
    id
    granted_by
    reason
    scope: (operation_type, jira_key optional)
    expires_at
    created_at
}
```
Bypass goes through the system (different door with camera), not around it.

4. **Visibility without spam:**
   - On override: post to channel (not just log)
   ```
   🚨 Emergency override used by @boris
   Operation: jira_update SCRUM-163
   Reason: production incident
   Expires: 10 min
   ```
   - Audit log: actor, payload hash, scope
   - Follow-up: "Done. Recommended: run /maro sync to reconcile."

5. **When to alert ops channel:**
   - Override in prod env
   - Override > N times per day
   - Override without managed section (most dangerous)
   - Repeated bypass attempts (possible abuse)
   - Auto-create ticket: "Investigate invariant bypass attempts"

**Key principle:** If override becomes a habit button, invariants are dead.

</specifics>

<notes>
## Additional Context

The core insight: "This is no longer a bot. It's a conversation-native version control system."

Git has these properties:
- Append-only history (commit log)
- Clear ownership (who committed what)
- Rebuildable state (checkout from log)

MARO should have the same guarantees. Phase 32 makes them inviolable — not through documentation but through code structure, type safety, and CI gates.

**Invariants to formalize:**
- I1: SuperMode = Sole UI Contract (users never see internal intents)
- I2: Slack = UI (handlers read-only, mutations via graph)
- I3: Commit Log = Append-Only (canonical messages rebuildable)
- I4: MANAGED_SECTION = Law (CI enforcement)
- I5: Draft Lifecycle = 3 User-Facing States (Drafting/Ready/Published)

Codebase assessment (gateway pattern status): To be determined during research.

</notes>

---

*Phase: 32-product-invariants*
*Context gathered: 2026-01-24*
