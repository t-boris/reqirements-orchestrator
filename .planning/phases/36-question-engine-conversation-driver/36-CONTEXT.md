# Phase 36: Question Engine — Conversation Driver

## Vision Summary

Transform MARO from "event recorder" to "conversation leader". Three concepts work together as a cohesive system:

1. **Questions as Tasks** — Questions become first-class entities in TaskPlan
2. **Active/Passive Mode** — Bot leads on @mention/BLOCKED, listens otherwise
3. **Question Budget** — Max 2 questions, then partial preview with choices

## Core Model

### Questions as TaskPlan Tasks

```
QuestionTask:
  task_id: str
  question_type: CONFIRM_SCOPE | COLLECT_FIELD | RESOLVE_CONFLICT | ASK_USER
  target_field: Optional[str]  # For COLLECT_FIELD
  options: Optional[list[str]]  # For CONFIRM_SCOPE
  question_text: str
  priority: int  # Lower = ask first
  status: PENDING | ANSWERED | SKIPPED
```

Question tasks execute like any other task — but their "execution" is posting a question and waiting for response.

### Active/Passive Mode State Machine

```
State: ACTIVE | PASSIVE

Transitions:
  PASSIVE → ACTIVE:
    - @mention in message
    - /command invoked
    - TaskPlan task becomes BLOCKED

  ACTIVE → PASSIVE:
    - TaskPlan completes (DONE or CANCELED)
    - 10min timeout with no user response
    - User explicitly cancels
```

When ACTIVE: Bot drives conversation, posts questions, follows up.
When PASSIVE: Bot listens, acknowledges, doesn't ask unprompted.

### Question Budget

```
QUESTION_BUDGET = 2

Rules:
1. Max 2 questions in a row without new user signal
2. After 2 unanswered questions → partial preview mode:
   - Show what we have (even incomplete)
   - [Proceed with gaps] [Wait for input] [Cancel]
3. New user message resets budget
```

## UX Feel

**Conversation-like with button options** — not interrogation, not wall of text.

Questions should feel natural:
- Short, specific question text
- 2-4 button options when possible
- "Other" escape hatch for freeform
- Visual progress indicator (what's complete, what's missing)

## QuestionCatalog Design

**Hybrid per question type:**

| Type | Catalog Approach |
|------|------------------|
| `CONFIRM_SCOPE` | Template — known patterns (parent selection, scope choice) |
| `COLLECT_FIELD` | LLM flexibility — field-aware prompts with examples |
| `RESOLVE_CONFLICT` | Template — A or B with clear descriptions |
| `ASK_USER` | Freeform fallback — LLM generates contextual question |

```python
class QuestionCatalog:
    """Registry of question templates and generators."""

    @staticmethod
    def confirm_scope(context: ScopeContext) -> QuestionTask:
        """Template: 'Stories only under SCRUM-166?' with known options."""

    @staticmethod
    def collect_field(field: str, draft: StructuredDraft) -> QuestionTask:
        """LLM-generated: field-aware prompt based on draft state."""

    @staticmethod
    def resolve_conflict(conflict: ConflictInfo) -> QuestionTask:
        """Template: 'A or B?' with deterministic options."""

    @staticmethod
    def ask_user(context: str, llm: LLM) -> QuestionTask:
        """LLM fallback: generate contextual question when no template fits."""
```

## Answer Mapping Design

**Hybrid by input type:**

| Input Type | Mapping Approach |
|------------|------------------|
| Button click | Deterministic — button value maps directly to StatePatch |
| Text reply | LLM parsing with schema validation |

```python
class StatePatch(BaseModel):
    """Unified format for state updates from user answers."""
    field: str           # Target field to update
    value: Any           # New value
    source: Literal["button", "text"]
    confidence: float    # 1.0 for buttons, LLM score for text

class AnswerMapper:
    def map_button_click(self, action_id: str, value: str) -> StatePatch:
        """Deterministic: action_id encodes field + expected value."""
        # action_id = "scope_choice:epics_only" → field="scope", value="EPICS_ONLY"

    def map_text_reply(self, text: str, expected_field: str, schema: dict) -> StatePatch:
        """LLM parses text against schema, validates, returns patch or asks for clarification."""
```

### Button Click Flow (Deterministic)

```
User clicks [Epics Only]
  → action_id="scope_choice:epics_only"
  → AnswerMapper.map_button_click()
  → StatePatch(field="scope", value="EPICS_ONLY", source="button", confidence=1.0)
  → Apply to draft, mark question answered
```

### Text Reply Flow (LLM-Parsed)

```
User types "just the epics, no stories"
  → AnswerMapper.map_text_reply(text, expected_field="scope", schema=ScopeSchema)
  → LLM: "Given expected field 'scope' with options [SINGLE, EPICS_ONLY, FULL_PLAN], parse: 'just the epics, no stories'"
  → LLM returns: {"field": "scope", "value": "EPICS_ONLY", "confidence": 0.95}
  → Validate against schema
  → If confidence < threshold → ask clarification
  → Else → StatePatch(field="scope", value="EPICS_ONLY", source="text", confidence=0.95)
```

## Key Invariants

1. **Question = Task** — Questions are tracked in TaskPlan, not ad-hoc text
2. **Budget = Hard Limit** — Never exceed 2 unanswered questions
3. **Buttons = Deterministic** — No LLM interpretation for button clicks
4. **Text = Schema-Validated** — LLM parses against expected structure
5. **Mode = Explicit** — Active/Passive transition logged and visible

## Integration Points

- **TaskPlan** (Phase 35) — Question tasks added to task list
- **StructuredDraft** (Phase 28) — Questions target draft fields
- **Status Card UI** — Question progress shown in card
- **Button Handlers** — Version-bound answers

## Example Flow

```
User: "@Maro create all user stories under SCRUM-166"

Bot enters ACTIVE mode.

TaskPlan:
  [OPERATE] Check duplicates → AUTO_EXECUTE
  [BUILD] Draft stories → BLOCKED (need scope clarification)
  [BUILD] Create in Jira → PENDING (needs approval)

Bot sees BLOCKED task, generates question:

QuestionTask:
  type: CONFIRM_SCOPE
  question: "Creating stories under SCRUM-166. What scope?"
  options: ["5-7 workstreams (I suggest)", "Give me titles", "Infer from decisions"]

Bot posts:
  "Creating stories under SCRUM-166. What scope?"
  [5-7 Workstreams] [Give Me Titles] [Infer from Decisions]

User clicks [5-7 Workstreams]
  → StatePatch(field="generation_mode", value="SUGGEST_WORKSTREAMS", confidence=1.0)
  → Task BLOCKED → READY
  → Draft generation proceeds
```

## Success Criteria

- [ ] Questions appear as tasks in TaskPlan
- [ ] Active/Passive mode transitions correctly
- [ ] Budget enforced (max 2 unanswered)
- [ ] Button clicks bypass LLM (deterministic)
- [ ] Text replies parsed with schema validation
- [ ] Partial preview shown when budget exhausted
- [ ] No silent loops or stops when info missing

---

*Context gathered: 2026-01-24*
*Ready for: /gsd:plan-phase 36*
