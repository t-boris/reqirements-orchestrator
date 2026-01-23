# Phase 28: Structured Draft Evolution

**Mantra:** Draft is a data structure representing the shape of work, not a paragraph of text.

**Core Shift:** From "bot collects text for a ticket" to "bot manages the form of a design object and the evolution of its structure."

---

## Fundamental Requirements

### R1. Draft must be a typed object, not text

Every Draft must have a form:

```python
class DraftKind(str, Enum):
    SINGLE_ITEM = "single_item"  # One ticket
    PLAN = "plan"                # Multiple items with structure

class DraftScope(str, Enum):
    SINGLE = "single"            # Just this one item
    EPICS_ONLY = "epics_only"    # Only epics, no stories
    FULL_PLAN = "full_plan"      # Epics + stories

class DraftItemStatus(str, Enum):
    PROPOSED = "proposed"        # Just suggested
    APPROVED = "approved"        # User confirmed
    COMMITTED = "committed"      # Created in Jira

class DraftItem(BaseModel):
    id: str
    issue_type: IssueType  # EPIC, STORY, TASK, BUG
    title: str
    goal: str
    constraints: list[str]
    status: DraftItemStatus

class StructuredDraft(BaseModel):
    kind: DraftKind
    item_type: IssueType  # Primary type (EPIC, STORY, etc.)
    scope: DraftScope
    version: int
    items: list[DraftItem]
    lifecycle: DraftLifecycle
    change_log: list[DraftChange]
```

Without this, the bot cannot "change form" because there is no form.

---

### R2. User decisions must mutate Draft form, not just be answered with text

Any user reply expressing a structural choice must:
1. Be recognized as `STRUCTURAL_DECISION`
2. Immediately mutate the Draft

Example:
```
User: "Split into multiple Epics"

→ Draft.kind = PLAN
→ Draft.item_type = EPIC
→ Draft.scope = EPICS_ONLY
→ Draft.items = []
→ Draft.version += 1
```

Only AFTER this mutation may the bot continue dialogue.

**Rule:** Every structural decision mutates the Draft state.

---

### R3. Bot must transition from questions to action

Forbidden:
```
ask → user answers → ask the same question
```

Required:
```
ask → user answers → apply → show updated structure → continue
```

After any user answer that selects an option, the bot must:
1. Update Draft
2. Acknowledge the change
3. Move to the next logical step

---

### R4. New intent: DRAFT_TRANSFORM

Distinct from:
- `CREATE` (create new draft)
- `REVIEW` (analysis)
- `CHANGE_REQUEST` (modify already committed truth)

`DRAFT_TRANSFORM` = change the form of the current draft.

Semantic triggers (via LLM, not keywords):
- "Split into…"
- "Merge these…"
- "Make this a plan…"
- "Only epics"
- "Break this down"
- "Group them"

Detection: semantic meaning = "change the structure of the object"

---

### R5. Draft must have a lifecycle

```
EMPTY
  → SINGLE_ITEM
    → PLAN
      → PLAN_REFINED
        → APPROVED
          → COMMITTED
```

The bot must know where it currently is.

**Rule:** Cannot ask for acceptance criteria while Draft is in PLAN stage.

---

### R6. Validation must depend on Draft form

| Draft.kind | What gets validated |
|------------|---------------------|
| SINGLE_ITEM | goal, boundaries, type |
| PLAN | presence of items, logical decomposition |
| STORY | acceptance criteria |
| EPIC | goal and scope, NOT acceptance criteria |

Current behavior violates this rule.

---

### R7. Bot must distinguish between:

- **"choice"** — user selects an option → ACTION
- **"opinion"** — user expresses preference → DISCUSSION
- **"question"** — user asks something → ANSWER

"Split into multiple Epics" is NOT an opinion, it's an ACTION.

**Rule:** If user input represents a decision, bot must act, not discuss.

---

### R8. After each Draft form change, bot must show the new form

Not just text, but structure:

```
Current structure:
Draft type: Epic Plan
Items:
1. Epic: Student Access
2. Epic: Content Platform
3. Epic: Infrastructure
```

This is a feedback loop for the human.

---

### R9. Draft must be versioned

Every structural change:
```python
Draft.version += 1
Draft.change_log.append(DraftChange(
    version=Draft.version,
    action="transform_to_plan",
    by_user_id=user_id,
    timestamp=now,
))
```

Every button/approval must be bound to the version.

---

### R10. Bot cannot repeat a question after receiving a direct answer

**Hard rule:** Repeating the same question after a direct answer is a system error.

---

### R11. Transition from decision to action is mandatory

| User Decision | System Action |
|---------------|---------------|
| Split | Create PLAN |
| Keep single | Lock SINGLE |
| Add stories | Create DraftItem type STORY |
| Only epics | Restrict scope |

---

### R12. Draft is no longer "text draft", it's a "design model"

**Philosophical but foundational:**

> Draft is a data structure representing the shape of work, not a paragraph of text.

---

## DoD Tests

### T1. Structural decision mutates state
1. User says "Split into epics"
2. Draft.kind changes from SINGLE_ITEM to PLAN
3. Draft.version increments
4. Bot shows new structure

### T2. Lifecycle enforced
1. Draft is in PLAN stage
2. Bot asks about decomposition (not acceptance criteria)
3. Only when item_type=STORY does bot ask AC

### T3. No question repetition
1. User answers "Only epics"
2. Bot does NOT ask "Would you like epics or full plan?" again
3. Draft.scope = EPICS_ONLY is locked

### T4. Version-bound approvals
1. Show preview (version=3)
2. User transforms structure (version=4)
3. Old approve button → "Outdated, please review new structure"

### T5. Form-dependent validation
1. Epic draft → validate goal, scope
2. Story draft → validate acceptance criteria
3. Plan draft → validate item count, decomposition logic
