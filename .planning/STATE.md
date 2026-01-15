# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-14)

**Core value:** Chat is the source of truth. The bot synchronizes conversations with Jira, proactively asking questions until requirements are complete, never creating half-baked tickets.
**Current focus:** v1.0 shipped — planning v1.1

## Current Position

Phase: 17 of 17 (Review Flow Fixes)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-01-15 — Completed 17-02-PLAN.md

Progress: ████████████████████ 100% (Phase 17)

## v1.0 Summary

**Shipped:** 2026-01-14

**Stats:**
- 10 phases, 43 plans completed
- 84 Python files, 13,248 LOC
- 24 days development (Dec 22 → Jan 14)
- 236 commits

**What shipped:**
- Thread-first Slack bot with Socket Mode
- LangGraph ReAct agent (extraction → validation → decision)
- Multi-provider LLM (Gemini, OpenAI, Anthropic)
- Skills: ask_user, preview_ticket, jira_create, jira_search
- Channel context from pins
- Dynamic personas (PM/Architect/Security)
- Docker deployment to GCE VM

## Next Milestone: v1.1 Context

**Planned phases:**
- Phase 11: Conversation History — fetch messages before @mention
- Phase 12: Onboarding UX — improve first-time experience

**Deferred from v1.0:**
- Conversation history fetching (bot only sees @mention message)
- `/help` command UX improvements

## Accumulated Context

### Decisions

All v1.0 decisions logged in PROJECT.md Key Decisions table.

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 11-02 | Preserve summary/buffer on disable | Allows context to persist if re-enabled later |
| 11-02 | UPSERT for enable operation | Handles new and re-enable cases in one operation |
| 11-03 | Pre-graph context injection | Context available to all nodes without individual fetches |
| 11-03 | Buffer 30, keep 20 raw, compress 10+ | Balance token cost vs context quality |
| 11.2-01 | 4s threshold for status | No spam for fast ops, visible feedback for slow ones |
| 11.2-01 | Dual client support | asyncio.to_thread() for sync client in async context |
| 11.2-02 | Predefined STATUS_MESSAGES | Consistent user-facing text for operations |
| 11.2-02 | Bottleneck identification | Pattern match on status to identify slow component |
| 11.2-02 | 15s/30s threshold updates | Limited updates to prevent status spam |
| 11.2-04 | Progress callback optional | Backward compatible with existing code |
| 11.2-04 | Factual error tone | No apologies, state what failed |
| 11.2-04 | Failure persists visible | Don't auto-delete so user sees error |
| 11.2-04 | Three action buttons | Retry/Skip/Cancel covers user choices |
| 12-01 | Post to channel not thread | Channels are workspaces, threads are conversations |
| 12-01 | Pin immediately | Quick-reference as persistent installation instructions |
| 12-01 | Non-blocking pin failure | Log warning but don't fail if no pin permission |
| 12-02 | Pattern match obvious cases | Greetings/perspective questions faster without LLM |
| 12-02 | LLM for nuanced classification | VAGUE_IDEA and CONFUSED need intent understanding |
| 12-02 | hint_select_* action pattern | Flexible routing for future hint button types |
| 12-03 | Ephemeral messages for examples | Don't spam channel with help content |
| 12-03 | Default /maro to help | Unknown subcommands show interactive help |
| 13-01 | Negation patterns highest priority | "don't create ticket" must override "create ticket" pattern |
| 13-01 | Pattern-matching-first | Check explicit patterns before LLM call for performance |
| 13-02 | Persona selection priority | intent_result.persona_hint > state.persona > architect default |
| 13-02 | Review response format | *{Persona} Review:* prefix for clarity |
| 13-03 | Discussion responds inline | No new thread creation for casual interactions |
| 13-03 | 1-2 sentence response limit | DISCUSSION_PROMPT enforces brevity |
| 13-04 | Scope gate with 3 options | Decision only / Full review / Custom - user controls ticket content |
| 13-04 | Modal-to-flow via context message | Scope submission posts message that triggers normal intent flow |
| 13-04 | Tests use direct module loading | importlib avoids circular imports in test suite |
| 13.1-01 | TICKET_ACTION patterns checked after NEGATION | "create subtasks for SCRUM-XXX" should not match "create ticket" |
| 13.1-01 | Ticket key normalized to uppercase | Jira uses uppercase keys; ensures consistency |
| 13.1-01 | Skip duplicate detection for bound threads | Prevents unnecessary Jira API calls |
| 14-01 | DECISION_APPROVAL patterns only with review_context | Prevents false positives in other contexts |
| 14-01 | review_context stored then cleared after posting | State lifecycle: review -> approval -> clear |
| 14-01 | Decision posted to channel not thread | Thread = thinking process, Channel = decisions |
| 15-01 | Continuation patterns only with has_review_context | Prevents "IdP: Okta" misclassification without review |
| 15-01 | NOT_CONTINUATION patterns checked first | "create new ticket" overrides continuation detection |
| 15-01 | LLM fallback uses context-aware prompt | Biases toward REVIEW_CONTINUATION with review context |
| 15-01 | review_context kept after continuation | Enables DECISION_APPROVAL after user answers questions |
| 16-01 | ADF conversion in service layer | JiraService handles text-to-ADF, not handlers |
| 16-01 | LLM-based content extraction | Extract structured content from conversation context |
| 16-01 | Separate prompts for update vs comment | Different formatting needs for descriptions vs comments |
| 16-01 | Message extraction from state.messages | Get latest HumanMessage for accurate user input |
| 17-02 | ReviewState enum with 4 lifecycle states | Track review_context: ACTIVE → CONTINUATION → APPROVED → POSTED |
| 17-02 | Block new review when active review exists | Prevents overwriting review_context (Bug #3) |
| 17-02 | Reference pattern detection | Detect "the architecture", "this review", "from above" for thread context |
| 17-02 | Thread context extraction for references | Include bot messages and long user messages when reference detected |

### Roadmap Evolution

- Phase 11.1 inserted after Phase 11: Jira Duplicate Handling (URGENT) — Allow users to link to existing tickets when duplicates found
- Phase 11.2 inserted after Phase 11: Progress & Status Indicators — Visual feedback during bot processing
- Phase 13 added: Intent Router — Route messages to Ticket/Review/Discussion flows before extraction
- Phase 13.1 inserted: Ticket Reference Handling — Handle "create subtasks for SCRUM-XXX", fix re-linking bug
- Phase 14 added: Architecture Decision Records — Auto-detect decisions, post to channel

### Deferred Issues

None (onboarding addressed in Phase 12).

### Pending Todos

1. ~~**Add intent detection to distinguish review requests from ticket creation** (graph)~~ → Promoted to Phase 13
   - File: `.planning/todos/pending/2026-01-15-intent-detection-review-vs-ticket.md` (archived)

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-01-15
Stopped at: Completed Phase 17 plan 02 (Review Flow Fixes)
Resume file: None
Next action: Phase 17 complete - Review flow and lifecycle fixes ready

## Phase 11 Summary (Complete)

**3 plans in 2 waves — ALL COMPLETE:**

Wave 1 (parallel):
- 11-01: History Fetching Service — `fetch_channel_history()`, `fetch_thread_history()`, `ConversationContext` [DONE]
- 11-02: Channel Listening State — DB model, `ListeningStore`, `/maro enable|disable|status` [DONE]

Wave 2:
- 11-03: Handler Integration — AgentState extension, context injection, rolling summary updates [DONE]

**Phase 11 accomplishments:**
- Two-layer context pattern (raw messages + compressed summary)
- Listening-enabled channels maintain rolling context
- Non-listening channels fetch on-demand at @mention
- Context injected into AgentState before graph runs

## Phase 11.1 Summary (Complete)

**1 plan — COMPLETE:**

- 11.1-01: Jira Duplicate Handling Interactive UX [DONE]

**Phase 11.1 accomplishments:**
- Enhanced duplicate metadata (status, assignee, updated time)
- LLM match explanation for best duplicate
- Interactive UX: Link to this, Add as info, Create new, Show more
- ThreadBindingStore for thread → Jira ticket bindings (in-memory MVP)
- Show More modal for viewing all duplicate matches
- Confirmation display after linking to existing ticket

## Phase 11.2 Summary (Complete)

**4 plans in 3 waves — ALL COMPLETE:**

Wave 1:
- 11.2-01: ProgressTracker Core — timing-based status (4s threshold), auto-cleanup [DONE]

Wave 2:
- 11.2-02: Skill-Specific Status — STATUS_MESSAGES dict, bottleneck identification at 15s/30s [DONE]

Wave 3:
- 11.2-04: Error Handling Protocol — set_error(), set_failure(), retry visibility, action buttons [DONE]

**Phase 11.2 accomplishments:**
- ProgressTracker with timing-based status (only shows for >4s operations)
- Skill-specific messages (searching_jira, creating_ticket, etc.)
- Long operation handling with bottleneck identification
- Error state methods with retry visibility (1/3, 2/3, 3/3)
- Progress callback pattern for service retry notifications
- Error action buttons (Retry, Skip Jira, Cancel) after failures

## Phase 12 Summary (Complete)

**3 plans in 2 waves — ALL COMPLETE:**

Wave 1 (parallel):
- 12-01: Channel Join Handler with Pinned Quick-Reference [DONE]
- 12-02: Hesitation Detection with LLM Classification [DONE]

Wave 2:
- 12-03: Interactive /maro help Command [DONE]

**Phase 12 accomplishments:**
- member_joined_channel event posts pinned quick-reference
- classify_hesitation() with LLM-based intent detection
- Contextual hints (GREETING, VAGUE_IDEA, PERSPECTIVE_NEEDED, CONFUSED)
- hint_select_* action handlers for persona buttons
- Interactive /maro help with example conversations
- /help redirects to interactive help
- Ephemeral example messages don't spam channel

**Core Principle:** MARO's onboarding personality is quiet, observant, helpful only when needed. Teaches by doing, not by lecturing.

## Phase 13 Summary (Complete)

**4 plans in 3 waves — ALL COMPLETE:**

Wave 1:
- 13-01: Intent Router Core — IntentType enum, pattern matching, LLM fallback [DONE]

Wave 2 (parallel):
- 13-02: Review Flow — review_node, persona-based analysis, *{Persona} Review:* format [DONE]
- 13-03: Discussion Flow — discussion_node, 1-2 sentence responses, inline replies [DONE]

Wave 3:
- 13-04: Scope Gate + Tests — Review-to-ticket button, scope modal, 53 regression tests [DONE]

**Phase 13 accomplishments:**
- Three-way intent classification: TICKET, REVIEW, DISCUSSION
- Pattern-matching-first with LLM fallback for ambiguous cases
- Negation patterns checked first ("don't create ticket" -> REVIEW)
- Review flow with persona-based analysis (security, architect, pm)
- Discussion flow for casual interactions (brief responses, no threads)
- Review-to-ticket transition with scope selection modal
- 53 regression tests for intent classification patterns

## Phase 13.1 Summary (Complete)

**1 plan — COMPLETE:**

- 13.1-01: Ticket Reference Handling [DONE]

**Phase 13.1 accomplishments:**
- TICKET_ACTION intent type with ticket_key and action_type fields
- 5 TICKET_ACTION patterns: create_subtask, add_subtask, update, add_comment, link
- Thread binding check at start of decision_node (skips duplicate detection if bound)
- Fixed re-linking bug: same-ticket actions proceed with action, don't re-link
- 21 new tests for TICKET_ACTION patterns (74 total tests pass)

## Phase 14 Summary (Complete)

**1 plan — COMPLETE:**

- 14-01: Architecture Decision Records [DONE]

**Phase 14 accomplishments:**
- DECISION_APPROVAL intent type with 9 detection patterns
- review_context field in AgentState for tracking recent reviews
- review_node saves context after analysis for decision detection
- decision_approval_node packages context for handler
- build_decision_blocks() for formatted channel posts
- LLM-based decision extraction from review context
- Decisions posted to channel (not thread) as permanent record

**Core Principle:** Thread = thinking process (architecture discussions), Channel = approved decisions (permanent record).

## Phase 15 Summary (Complete)

**1 plan — COMPLETE:**

- 15-01: Review Conversation Flow [DONE]

**Phase 15 accomplishments:**
- REVIEW_CONTINUATION intent type with 5 answer patterns
- Context-aware intent classification (has_review_context parameter)
- review_continuation_node synthesizes answers and asks for approval
- NOT_CONTINUATION patterns prevent false positives
- Handler posts continuation with persona prefix
- 24 tests verify pattern matching for common answer formats

**Core Principle:** When user replies with answers after a review, continue the conversation instead of misclassifying as ticket creation.

## Phase 16 Summary (Complete)

**1 plan — COMPLETE:**

- 16-01: Ticket Operations [DONE]

**Phase 16 accomplishments:**
- Three new JiraService methods: update_issue(), add_comment(), create_subtask()
- All methods support ADF conversion, dry-run mode, progress callbacks
- Content extraction prompts (UPDATE_EXTRACTION_PROMPT, COMMENT_EXTRACTION_PROMPT)
- Helper functions: _extract_update_content(), _extract_comment_content()
- Replaced stubs for update and add_comment actions with real API calls
- ticket_action_node passes user_message and review_context for extraction
- Error handling with user-friendly Slack messages

**Core Principle:** Enable full ticket lifecycle management beyond creation. Use LLM to extract structured, actionable content from conversations instead of raw message dumps.

## Phase 17 Summary (Complete)

**2 plans — COMPLETE:**

- 17-01: Handler Integration Fixes [DONE]
- 17-02: Review Flow Lifecycle and Thread Context [DONE]

**Phase 17 accomplishments:**
- ReviewState enum with 4 lifecycle states (ACTIVE, CONTINUATION, APPROVED, POSTED)
- review_node checks for existing active review before overwriting (prevents Bug #3)
- Reference detection: "the architecture", "this review", "from above" patterns
- Thread context extraction when references detected (fixes Bug #2)
- decision_approval_node marks state=POSTED before clearing (helps debug Bug #4)
- 22 comprehensive tests covering reference detection and lifecycle management

**Core Principle:** Preserve review context through the full lifecycle until decision is posted to channel. Detect when users reference prior content and include that context in extraction.
