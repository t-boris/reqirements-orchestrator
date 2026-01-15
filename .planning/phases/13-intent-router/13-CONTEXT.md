# Phase 13: Intent Router - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

MARO должен понимать **что именно от него хотят** до того, как начинать работу. Сейчас все сообщения идут в один конвейер (extraction → validation → duplicate check → preview), что делает бота "тикет-машиной".

### Три режима работы

| Intent | Где живёт | Что происходит |
|--------|-----------|----------------|
| **TICKET** | Тред | Extract → Validate → Dedupe → Preview → Create |
| **REVIEW** | Тред | Архитектурный анализ, обсуждение, вопросы |
| **DISCUSSION** | В месте @mention | Один короткий ответ, без state |

### Ключевое понимание

> **Архитектура = процесс мышления (тред)**
> **Решение = состояние системы (канал)**

- Тред — это стол, на котором разложены чертежи
- Канал — это доска, где висят утверждённые решения

### ReviewFlow: Conversational thinking

Когда человек говорит "@Maro propose an architecture":
1. MARO создаёт тред
2. Пишет анализ как senior engineer, который размышляет вслух:
   - компоненты и потоки
   - риски
   - альтернативы
   - открытые вопросы
3. Обсуждение продолжается в треде
4. Когда решение принято ("let's go with this") — MARO авто-детектит и постит результат в канал

### "Review this" (REVIEW_ARTIFACT)

Smart inference → based on thread history → otherwise ask.

1. **Inspect thread history** — найти последний meaningful chunk:
   - code block?
   - architecture proposal?
   - Jira preview?
   - requirements draft?

2. **Infer review type** из контента:
   - code/config → Security или Architect
   - architecture text → Architect
   - requirements draft → PM

3. **Act without asking** если confidence > threshold

4. **Fallback to buttons** если непонятно:
   > "Do you mean: the architecture above / the Jira draft / the last message?"

**Правило:** MARO assumes competence first, asks only when confidence is low.

### DiscussionFlow: Вежливость

DISCUSSION = один ответ, без state, без thread creation.

```
User: @Maro hi
MARO: Hi! I help turn discussions into Jira tickets and review ideas as PM, Architect, or Security.
      What would you like to work on?
```

**И всё. Стоп.**

DISCUSSION никогда не должен:
- создавать тред
- создавать draft
- вызывать Jira
- запускать validators

### Transition: Review → Ticket

После review, если user говорит "create a ticket for this":

1. **Scope gate** (один короткий вопрос):
   > "Create ticket for: [1] Final decision [2] Full proposal [3] Specific part?"

2. **Seamless handoff** — MARO использует review-контекст:
   - вычленяет нужный кусок
   - автоматически заполняет title, problem, architecture notes
   - сразу показывает preview

### Guardrails

**ReviewFlow is read-only with respect to Jira.**

- `jira_search`, `jira_create`, `jira_update` заблокированы code-level
- Override только через explicit mode switch:
  - `/maro ticket`
  - `@Maro create a ticket for this`
  - Scope gate confirmation

После override → switch to TicketFlow, guardrails lifted.

</vision>

<essential>
## What Must Be Nailed

Все три одинаково важны:

- **Intent detection accuracy** — Bot must correctly classify TICKET vs REVIEW vs DISCUSSION
- **Review quality** — Architectural analysis must be thoughtful (conversational, like senior engineer)
- **Thread/channel separation** — Process in threads, results in channel

</essential>

<specifics>
## Specific Ideas

### Intent classification returns structured object:
```json
{
  "intent": "TICKET" | "REVIEW" | "DISCUSSION",
  "confidence": 0.0-1.0,
  "persona_hint": "pm"|"architect"|"security"|null,
  "topic": "..."|null,
  "reasons": ["pattern: propose architecture", "keyword: risks"]
}
```

### Pattern matching + explicit overrides:
- "create a ticket" = TICKET (force)
- "review as security" = REVIEW (force)
- "don't create a ticket" = REVIEW (force)
- `/maro ticket` = TICKET (force)
- `/maro review` = REVIEW (force)

### Architecture decision auto-detect:
When someone says "let's go with this" after review, MARO:
1. Detects approval
2. Posts to channel: "📐 Architecture decision: [summary] (see thread #123)"

### Review → Ticket mental model:
- Review = generates structured artifacts
- Ticket = packages selected artifacts into Jira form
- Scope gate = user selects what becomes artifact

</specifics>

<notes>
## Additional Context

### Ментальная модель flows:

| Intent | Поведение |
|--------|-----------|
| TICKET | Создать рабочий тред, pipeline |
| REVIEW | Создать рабочий тред, анализ |
| DISCUSSION | Один короткий ответ, без state |

DISCUSSION — это "вежливость".
TICKET и REVIEW — это "работа".

### Invariant для кода:

> ReviewFlow is read-only with respect to Jira.
> Jira operations require an explicit mode switch to TicketFlow.

### DoD (Definition of Done):

- [ ] IntentRouter node выбирает ветку: Ticket/Review/Discussion
- [ ] Review ветка не вызывает Jira tools и не строит draft
- [ ] Discussion ветка отвечает один раз и останавливается
- [ ] Логи: intent, confidence, reasons
- [ ] Тесты: 10–20 фраз на каждую ветку (регрессия)
- [ ] [Turn into Jira ticket] / scope gate после review
- [ ] Auto-detect architecture decisions → post to channel

</notes>

---

*Phase: 13-intent-router*
*Context gathered: 2026-01-15*
