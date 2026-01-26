# Phase 39: Intent Classification v2 — Context

## Source

Technical specification provided by user (2026-01-25).

---

## ТЗ: Intent Classification System (v2)

### 0. Цель

Стабильно определять, что пользователь хочет сделать, в условиях:
- многопользовательского Slack-канала
- неполных/неявных формулировок
- активных артефактов (draft, decision, workitem, jira links)
- multi-intent сообщений

Система должна:
1. выбирать Mode (5 супер-модов)
2. выбирать Intent (внутренний тип)
3. при необходимости возвращать TaskPlan (несколько задач)
4. быть детерминированной "насколько возможно", с явными правилами fallback
5. не запускать неправильные флоу (особенно Jira writes) при сомнении

---

### 1. Термины

#### 1.1 SuperMode (user-facing)
- **BUILD** — формирование/изменение draft/структуры работ
- **THINK** — архитектура/анализ/ревью без тикетов
- **DECIDE** — фиксация/изменение decision, утверждения
- **OPERATE** — действия над Jira/Sync/команды
- **CHAT** — приветствие, разговор, мета-вопросы о боте

#### 1.2 Internal Intent (engine-facing)

Примерный набор (может маппиться на текущие 13):

| SuperMode | Intents |
|-----------|---------|
| BUILD | DRAFT_REFINE, DRAFT_TRANSFORM, WORKITEM_CREATE (как draft->preview, без Jira write) |
| THINK | REVIEW_TOPIC, REVIEW_ARTIFACT |
| DECIDE | DECISION_RECORD, DECISION_UPDATE, DECISION_DEPRECATE, DECISION_LINK |
| OPERATE | JIRA_COMMAND, JIRA_SEARCH, SYNC_REQUEST, TICKET_ACTION (create under existing) |
| CHAT | DISCUSSION, META, OPS_DEBUG |
| special | AMBIGUOUS (требуется выбор пользователя) |

Примечание: структура намеренно допускает "alias" к текущим 13 интентам для совместимости.

#### 1.3 ContextSpec / ContextPacket
- **ContextSpec** — краткое описание того, какой контекст нужен
- **ContextPacket** — итоговый контекст, который подаётся в LLM

---

### 2. Входы классификатора

#### 2.1 Event input (обязательные поля)
- channel_id
- thread_ts (или None)
- message_ts
- user_id
- text (или rendered_text если blocks)
- is_mention (bool)
- is_command (bool + command payload)

#### 2.2 State input (из DB/canonical state)
- active_draft: exists? + summary + shape + required_fields_missing
- active_taskplan: exists? + blocked_task? + owner + ui_message_ts
- anchor: {type: NONE|DECISION|WORKITEM|JIRA, id, message_ts}
- channel_registry_snapshot: кратко (активные workitems/decisions/jira links)
- permissions: роль автора (owner/admin/member), can_write_jira?

#### 2.3 Context slice (history)
- last N messages normalized (N=10..20)
- обязательно включить anchor/root message если thread

---

### 3. Выходы классификатора

#### 3.1 IntentEnvelope (единый формат)

Классификатор всегда возвращает один из вариантов:

**A) SingleAction**
```json
{
  "kind": "single",
  "mode": "BUILD|THINK|DECIDE|OPERATE|CHAT",
  "intent": "DRAFT_REFINE|REVIEW_TOPIC|...",
  "confidence": 0.0,
  "margin": 0.0,
  "targets": {"jira_key": null, "decision_id": null, "workitem_id": null},
  "risk_level": "safe|write|mass_write|destructive",
  "reason": "string",
  "alternatives": [{"mode": "...", "intent": "...", "score": 0.0}]
}
```

**B) TaskPlan**
```json
{
  "kind": "plan",
  "tasks": [
    {"mode": "...", "intent": "...", "risk_level": "...", "targets": {...}, "reason": "..."}
  ],
  "confidence": 0.0,
  "margin": 0.0,
  "requires_confirm": true|false
}
```

**C) AmbiguousChoice**
```json
{
  "kind": "ambiguous",
  "choices": [
    {"label": "...", "mode": "...", "intent": "...", "risk_level": "...", "targets": {...}}
  ],
  "reason": "why unclear"
}
```

#### 3.2 Требования к метрикам
- **confidence** — score top choice
- **margin** = top_score - second_score
- **alternatives** — top 2–3 кандидата

---

### 4. Архитектура: 2-stage классификация

#### Stage 0: Deterministic pre-gates (инварианты)

До LLM, система применяет инварианты по state (не по словам):

1. **Terminal handling**
   - если is_command с известным слэшем → mode=OPERATE (или CHAT для /help)
   - если intent in {DISCUSSION,META,OPS_DEBUG} → граф завершается после одного ответа

2. **Active TaskPlan continuation**
   - если есть active_taskplan и он BLOCKED и сообщение в том же thread → это "answer to question" (route → AnswerMapper), bypass intent classification

3. **Draft priority gate**
   - если active_draft.exists == true и сообщение в том же thread/channel scope:
     - LLM должен рассматривать BUILD intents как приоритетные
     - THINK/REVIEW допускается только если явно про анализ и не про структуру draft

4. **Risk guard**
   - если предполагается Jira write (risk_level ∈ write/mass/destructive) и margin < threshold → вернуть kind=ambiguous (требуется выбор), а не выполнять

**Важно:** это не pattern matching по словам, это state-based safety policy.

#### Stage 1: Mode classification (LLM)

LLM выбирает:
- mode
- is_multi_intent (bool)
- top candidates with scores

Выход Stage 1:
```json
{
  "mode_candidates": [{"mode":"BUILD","score":0.72}, ...],
  "multi_intent": true,
  "reasons": [...]
}
```

#### Stage 2: Intent / TaskPlan (LLM)

LLM получает:
- top mode
- state hints (anchor type, draft exists, blocked task, permissions)

и возвращает IntentEnvelope (single/plan/ambiguous).

Extraction of parameters (jira key, action_type) делается минимально: только identifiers, без тяжёлой семантики.

---

### 5. Мульти-интент: правила

Если LLM считает multi-intent:
- вернуть kind=plan
- каждая task должна иметь: mode, intent, risk_level, target
- Executor обязан упорядочить по safety:
  1. OPERATE (safe reads)
  2. BUILD (draft)
  3. THINK (analysis)
  4. DECIDE (approval)
  5. OPERATE (writes) только с confirm

**Правило:** History = context, но задачи берём только из trigger message, чтобы бот не "выдумывал" новые работы из старых обсуждений.

---

### 6. Ambiguity policy (когда спрашивать)

Классификатор обязан возвращать kind=ambiguous если:
- margin < 0.15 (настраиваемо)
- top intent предполагает risk_level != safe и confidence < 0.75
- конфликт целей: BUILD vs THINK (draft questions vs review) при активном draft
- target неопределён (например "update this" без anchor)

**AmbiguousChoice UI:**
- 2–4 кнопки выбора
- каждая кнопка содержит payload для детерминированного routing

---

### 7. Определение target (без "магии")

Target resolution делается вне LLM, насколько возможно:
- если anchor type = WORKITEM → workitem_id известен
- если anchor type = DECISION → decision_id известен
- если в тексте есть Jira key → можно LLM/regex извлечь, но это отдельный extractor

LLM должен:
- подтверждать, какой target использовать (из предложенных)
- но не "придумывать" новые ids

---

### 8. Интерфейс для LangGraph

#### 8.1 Node: intent_router_node
- Input: Event + State snapshot
- Output: IntentEnvelope

#### 8.2 Router: route_after_intent
- kind=single → route by intent
- kind=plan → task_decomposer_flow
- kind=ambiguous → ask_user_flow (buttons)

#### 8.3 Terminal rules
- CHAT intents → single response node → END
- OPS_DEBUG/META → explain node → END

---

### 9. Нефункциональные требования (NFR)

#### Determinism
- Same input + same state → same output (в пределах LLM variance)
- Для этого:
  - используем temperature=0
  - фиксируем system prompt
  - используем structured JSON output schema

#### Observability
Логировать в DB:
- input summary
- top candidates
- confidence/margin
- chosen envelope
- reason
- duration + token usage

#### Safety
- Jira writes требуют подтверждения, если не "explicit command"
- Любой destructive operation требует explicit confirm независимо от confidence

#### Performance
- Stage 1 должен быть дешёвым (короткий prompt, маленький context slice)
- Stage 2 вызывается только если нужно

---

### 10. Acceptance Criteria (DoD)

1. При активном draft вопрос "Do you think only one epic is enough?" → DRAFT_REFINE, не REVIEW
2. "hello" / casual chat → CHAT → один ответ → END, без циклов
3. Multi-intent "create stories and check duplicates" → kind=plan, tasks ordered safely
4. Любая Jira write при низкой margin → kind=ambiguous с выбором
5. При BLOCKED Question task, следующий user message в thread маппится как answer (bypass classifier)
6. Все outputs соответствуют JSON schema, ошибки парсинга не приводят к "silent stop" — fallback to ambiguous

---

### 11. Примечания по "no pattern matching"

**Запрещено:** использовать keyword rules как основной механизм классификации.

**Разрешено:**
- state-based gates (draft exists, anchor type, blocked tasks)
- command detection (/maro …)
- identifier extraction (jira key) как отдельный extractor
- margin-based ambiguity policy

---

## Key Changes from Current System

| Current | Target |
|---------|--------|
| Single IntentResult OR TaskPlanProposal | Unified IntentEnvelope (single/plan/ambiguous) |
| confidence only | confidence + margin + alternatives |
| LLM-first classification | Stage 0 gates → Stage 1 mode → Stage 2 intent |
| REVIEW allowed with active draft | Draft priority gate blocks REVIEW |
| DISCUSSION can loop | Terminal intents = single response → END |
| Implicit target resolution | Explicit target from anchor, LLM confirms |
