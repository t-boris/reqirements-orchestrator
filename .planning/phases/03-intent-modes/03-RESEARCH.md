# Phase 3: Intent & Modes - Research

**Researched:** 2026-02-02
**Domain:** LLM-based intent classification with provider-agnostic abstraction
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Python ecosystem for building a multi-stage intent classification system with LLM routing. The standard approach uses **LiteLLM** for provider-agnostic LLM access and **Instructor** (or **PydanticAI**) for structured output with automatic validation and retries.

Key finding: Don't hand-roll JSON parsing or retry logic. Instructor handles validation failures by passing error messages back to the LLM and retrying automatically. For edge cases where LLM still produces malformed JSON, use `json_repair` as a fallback layer.

For confidence scoring, log probabilities are the most reliable method — verbalized confidence ("I am 80% sure") is unreliable and tends toward overconfidence.

**Primary recommendation:** Use LiteLLM for multi-provider access + Instructor for structured classification output with Pydantic validation. Add json_repair as safety net. Implement PreGates as simple pattern matching before LLM calls.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| litellm | 1.57+ | Multi-provider LLM abstraction | 100+ providers, OpenAI format, 8ms P95 latency |
| instructor | 1.8+ | Structured output extraction | 3M+ downloads, auto-retries, Pydantic validation |
| pydantic | 2.x | Schema definition & validation | Industry standard, JSON schema generation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json-repair | 0.30+ | Fix malformed LLM JSON | Fallback when structured output fails |
| tenacity | 8.x | Retry logic | Complex retry patterns beyond Instructor |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| LiteLLM | PydanticAI | PydanticAI is full agent framework, heavier; LiteLLM is lighter for just LLM calls |
| Instructor | PydanticAI | PydanticAI from Pydantic team, better for full agents; Instructor simpler for just structured output |
| json-repair | LLM self-correction | json_repair is faster, deterministic; LLM retry adds latency |

**Installation:**
```bash
pip install litellm instructor pydantic json-repair
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── intent/
│   ├── __init__.py
│   ├── pregates.py         # Deterministic pre-routing
│   ├── router.py           # LLM-based classification
│   ├── schemas.py          # Pydantic models for intents
│   └── safety.py           # Safety evaluator
├── llm/
│   ├── __init__.py
│   ├── client.py           # LiteLLM wrapper
│   ├── structured.py       # Instructor integration
│   └── repair.py           # JSON repair fallback
└── modes/
    ├── __init__.py
    ├── base.py             # SuperMode base class
    ├── create.py           # CREATE mode handler
    ├── modify.py           # MODIFY mode handler
    ├── record.py           # RECORD mode handler
    └── converse.py         # CONVERSE mode handler
```

### Pattern 1: PreGates (Deterministic Pre-Routing)
**What:** Pattern matching before LLM — catches commands, button clicks, explicit actions
**When to use:** Always as first stage — saves latency, ensures predictability
**Example:**
```python
from enum import Enum
from dataclasses import dataclass

class PreGateResult(Enum):
    COMMAND = "command"        # Slash command detected
    ACTION = "action"          # Button click detected
    APPROVAL = "approval"      # Explicit approve/object
    PASS_THROUGH = "pass"      # Needs LLM classification

@dataclass
class PreGateOutput:
    result: PreGateResult
    data: dict | None = None

def check_pregates(message: str, event_type: str) -> PreGateOutput:
    """Deterministic pre-routing before LLM."""
    # Slash commands
    if message.startswith("/maro"):
        return PreGateOutput(PreGateResult.COMMAND, {"command": message})

    # Button actions (from Slack event type)
    if event_type == "block_actions":
        return PreGateOutput(PreGateResult.ACTION)

    # Explicit approval keywords
    approval_patterns = ["approved", "lgtm", "ship it", "+1"]
    if any(p in message.lower() for p in approval_patterns):
        return PreGateOutput(PreGateResult.APPROVAL)

    # Pass to LLM
    return PreGateOutput(PreGateResult.PASS_THROUGH)
```

### Pattern 2: Structured LLM Classification with Instructor
**What:** Use Pydantic models for LLM output schema, Instructor for validation/retries
**When to use:** LLM-based intent classification
**Example:**
```python
from pydantic import BaseModel, Field
from enum import Enum
import instructor
import litellm

class SuperMode(str, Enum):
    CREATE = "create"      # New entity creation
    MODIFY = "modify"      # Edit existing entity
    RECORD = "record"      # Capture decision/info
    CONVERSE = "converse"  # Chat, clarify, explore

class IntentClassification(BaseModel):
    """LLM classification output schema."""
    mode: SuperMode
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    entities_mentioned: list[str] = Field(default_factory=list)

# Patch LiteLLM with Instructor
client = instructor.from_litellm(litellm.completion)

async def classify_intent(message: str, context: str) -> IntentClassification:
    """Classify message intent using LLM with structured output."""
    return await client.chat.completions.create(
        model="gemini/gemini-2.0-flash",  # LiteLLM format
        response_model=IntentClassification,
        max_retries=2,  # Auto-retry on validation failure
        messages=[
            {"role": "system", "content": CLASSIFICATION_PROMPT},
            {"role": "user", "content": f"Context: {context}\n\nMessage: {message}"},
        ],
    )
```

### Pattern 3: Confidence Threshold with Safe Fallback
**What:** Fall back to CONVERSE mode when LLM isn't confident
**When to use:** Prevent side-effects on ambiguous input
**Example:**
```python
CONFIDENCE_THRESHOLD = 0.7

async def route_with_safety(message: str, context: str) -> SuperMode:
    """Route with confidence threshold - fail safe to CONVERSE."""
    result = await classify_intent(message, context)

    # Low confidence → safe fallback
    if result.confidence < CONFIDENCE_THRESHOLD:
        logger.info(f"Low confidence ({result.confidence}), falling back to CONVERSE")
        return SuperMode.CONVERSE

    # CREATE/MODIFY require higher confidence
    if result.mode in (SuperMode.CREATE, SuperMode.MODIFY):
        if result.confidence < 0.85:
            logger.info(f"Side-effect mode with medium confidence, falling back")
            return SuperMode.CONVERSE

    return result.mode
```

### Pattern 4: JSON Repair Fallback Layer
**What:** Repair malformed JSON when structured output fails
**When to use:** Belt-and-suspenders for edge cases
**Example:**
```python
import json
from json_repair import repair_json

def safe_parse_json(text: str) -> dict:
    """Parse JSON with repair fallback."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = repair_json(text)
        return json.loads(repaired)
```

### Anti-Patterns to Avoid
- **Verbalized confidence:** Don't ask LLM "rate your confidence 1-10" — it hallucinates numbers
- **Single retry without feedback:** Instructor sends validation errors back to LLM, don't just retry blindly
- **LLM for everything:** Use PreGates for deterministic cases — faster and more reliable
- **No fallback mode:** Always have CONVERSE as safe default when uncertain
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-provider LLM calls | Custom API wrappers per provider | LiteLLM | 100+ providers, consistent format, error mapping |
| Structured LLM output | JSON parsing + manual validation | Instructor | Auto-retries, Pydantic validation, type safety |
| Malformed JSON repair | Custom regex/string fixes | json_repair | Handles all common LLM mistakes reliably |
| Retry with backoff | Simple loops | Instructor's max_retries or tenacity | Proper backoff, error handling |
| JSON schema generation | Manual schema writing | Pydantic model_json_schema() | Auto-generated, always in sync with types |

**Key insight:** LLM output parsing has many edge cases (unescaped quotes, trailing commas, missing brackets). The json_repair library handles them all. Instructor handles the retry-with-feedback loop that dramatically improves success rates.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Trusting Verbalized Confidence
**What goes wrong:** LLM says "I'm 95% confident" but is completely wrong
**Why it happens:** LLMs imitate human confidence patterns, tend toward overconfidence
**How to avoid:** Use log probabilities if available, or treat verbalized confidence as noisy signal with conservative thresholds
**Warning signs:** High stated confidence on clearly ambiguous inputs

### Pitfall 2: No PreGates Before LLM
**What goes wrong:** Latency spike, costs increase, LLM hallucinates on obvious cases
**Why it happens:** Sending everything to LLM when pattern matching would suffice
**How to avoid:** Implement PreGates that catch commands, actions, explicit keywords
**Warning signs:** LLM calls for slash commands, button clicks, "approved" messages

### Pitfall 3: Single Retry Without Context
**What goes wrong:** Same error repeated, wasted retries
**Why it happens:** Retry doesn't tell LLM what went wrong
**How to avoid:** Use Instructor — it passes validation errors back to LLM with retry
**Warning signs:** Same malformed output on retry

### Pitfall 4: Side-Effects on Low Confidence
**What goes wrong:** Creates wrong entity type, modifies wrong item
**Why it happens:** Acting on ambiguous classification
**How to avoid:** Require higher confidence for CREATE/MODIFY, always fall back to CONVERSE
**Warning signs:** "I meant to create a bug, not a story" user complaints

### Pitfall 5: Blocking on LLM in Event Handler
**What goes wrong:** Slack times out (3 second limit for ack)
**Why it happens:** LLM call takes 1-3 seconds, plus retries
**How to avoid:** ack() immediately, then process async
**Warning signs:** Slack shows "operation timed out" errors
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official sources:

### LiteLLM Basic Usage
```python
# Source: https://docs.litellm.ai/docs/
import litellm

# Unified API for any provider
response = await litellm.acompletion(
    model="gemini/gemini-2.0-flash",  # or "gpt-4", "claude-3-opus", etc.
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

### Instructor with LiteLLM
```python
# Source: https://docs.litellm.ai/docs/tutorials/instructor
import instructor
import litellm
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int

client = instructor.from_litellm(litellm.completion)

user = client.chat.completions.create(
    model="gpt-4o-mini",
    response_model=User,
    messages=[{"role": "user", "content": "Extract: John is 25 years old"}],
)
print(user)  # User(name='John', age=25)
```

### Instructor with Retries
```python
# Source: https://python.useinstructor.com/
from pydantic import BaseModel, field_validator

class ValidatedOutput(BaseModel):
    category: str
    confidence: float

    @field_validator('confidence')
    @classmethod
    def check_range(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('confidence must be between 0 and 1')
        return v

# Instructor retries with validation errors sent to LLM
result = client.chat.completions.create(
    model="gpt-4o-mini",
    response_model=ValidatedOutput,
    max_retries=3,  # Will retry up to 3 times with error feedback
    messages=[...],
)
```

### JSON Repair Fallback
```python
# Source: https://github.com/mangiucugna/json_repair
from json_repair import repair_json
import json

# LLM returned malformed JSON
broken = '{"mode": "create", "confidence": 0.9,}'  # trailing comma

try:
    data = json.loads(broken)
except json.JSONDecodeError:
    fixed = repair_json(broken)
    data = json.loads(fixed)  # Works: {'mode': 'create', 'confidence': 0.9}
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing | Instructor structured output | 2024 | 90%+ reduction in parsing code |
| Per-provider SDK | LiteLLM unified API | 2024 | Single API for 100+ providers |
| LangChain for everything | Lighter tools (LiteLLM + Instructor) | 2025 | Less complexity, faster |
| Verbalized confidence | Log probability extraction | 2025 | More reliable uncertainty |

**New tools/patterns to consider:**
- **PydanticAI:** From the Pydantic team, full agent framework with graphs and durable execution. Consider for complex multi-step agents.
- **Semantic Router:** For very high-throughput routing with fixed intents, embedding-based classification is faster than LLM calls.

**Deprecated/outdated:**
- **Manual OpenAI/Anthropic SDK switching:** Use LiteLLM instead
- **Custom retry loops:** Use Instructor's built-in max_retries
- **json.loads() only:** Always have json_repair fallback for LLM output
</sota_updates>

<open_questions>
## Open Questions

Things that couldn't be fully resolved:

1. **Log probability access across providers**
   - What we know: OpenAI and some providers expose logprobs
   - What's unclear: Whether Gemini/Claude expose usable logprobs via LiteLLM
   - Recommendation: Start with verbalized confidence + conservative thresholds, add logprobs if provider supports

2. **Optimal confidence thresholds**
   - What we know: Lower thresholds = more false positives, higher = more fallbacks
   - What's unclear: Exact thresholds for MARO use case
   - Recommendation: Start conservative (0.7 for CONVERSE, 0.85 for CREATE/MODIFY), tune based on observed behavior
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [LiteLLM Documentation](https://docs.litellm.ai/docs/) - Getting started, providers, structured output
- [Instructor Documentation](https://python.useinstructor.com/) - Retries, validation, multi-provider
- [json_repair GitHub](https://github.com/mangiucugna/json_repair) - JSON repair library
- [PydanticAI Documentation](https://ai.pydantic.dev/) - Agent framework, structured outputs

### Secondary (MEDIUM confidence)
- [LiteLLM PyPI](https://pypi.org/project/litellm/) - Version 1.57+, MIT license
- [Instructor PyPI](https://pypi.org/project/instructor/) - Version 1.8+, 3M+ downloads
- [Intent Classification Best Practices](https://www.patronus.ai/ai-agent-development/ai-agent-routing) - Routing patterns
- [LLM Confidence Scores](https://github.com/VATBox/llm-confidence) - Log probability extraction

### Tertiary (LOW confidence - needs validation)
- Semantic Router for high-throughput routing (not tested for this use case)
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: LiteLLM + Instructor for LLM abstraction
- Ecosystem: json_repair, Pydantic, tenacity
- Patterns: PreGates, structured output, confidence thresholds, safety fallback
- Pitfalls: Verbalized confidence, blocking handlers, no fallback

**Confidence breakdown:**
- Standard stack: HIGH - verified with official docs, widely used
- Architecture: HIGH - from official examples and best practices articles
- Pitfalls: HIGH - documented in multiple sources
- Code examples: HIGH - from official documentation

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - LLM ecosystem moves fast but core patterns stable)
</metadata>

---

*Phase: 03-intent-modes*
*Research completed: 2026-02-02*
*Ready for planning: yes*
