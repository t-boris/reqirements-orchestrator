# Phase 37: Unified Question Engine - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<vision>
## How This Should Work

Один движок для всех вопросов — и для тикетов, и для architecture review. Разница только в источнике вопросов (provider), но механизм един.

**Question Engine отвечает за:**
- Когда задавать вопрос (BLOCKED / ambiguity / conflict)
- Как показывать (кнопки, budget, active/passive)
- Как принимать ответ (button→deterministic, text→LLM parse)
- Как маппить в state (patch)
- Как не спамить (throttle, 2-question budget)

Это одинаково работает и для тикетов, и для review.

**Два провайдера:**

A) **CatalogProvider** (для тикетов / structured work)
- Вопросы предсказуемые
- Заполняют конкретные поля WorkItemDraft
- Жёсткая схема: title/problem/ac/constraints/parent/issue_type
- Кнопки и enum-выборы

B) **FreeformProvider** (для review / architecture thinking)
- Вопросы генерятся LLM-ом, но в строгом формате
- Уточнение требований
- Проверка предположений
- Выявление рисков/границ
- Запрос артефакта (diagram, constraints, tradeoffs)

Даже freeform вопрос возвращает структуру:
```
ReviewQuestion {
  goal: "disambiguate transport layer"
  question: "Do we need real-time guarantees or is eventual ok?"
  expected_answer_type: "choice|text|number"
  options: [...]
  maps_to: "review_state.assumptions.realtime"
}
```

**ReviewState** вместо WorkItemDraft для review:
```
ReviewState {
  topic
  assumptions[]
  constraints[]
  risks[]
  open_questions[]
  proposed_decisions[]
}
```

Decision Engine потом может оформить decision или предложить "turn into tickets".

</vision>

<essential>
## What Must Be Nailed

- **Унифицированный UX** — кнопки, budget, throttle одинаковые для обоих путей. Пользователь не должен чувствовать разницу в интерфейсе.

- **Структурированный FreeformProvider** — даже LLM-generated вопросы должны быть структурными (goal, maps_to, expected_answer_type). Гибкость по тексту, структура по смыслу.

- **ReviewState как target** — маппинг ответов не в WorkItemDraft, а в ReviewState для review контекста. Каждый ответ уточняет assumptions, constraints, risks.

</essential>

<specifics>
## Specific Ideas

**Почему не две отдельные системы:**
- UX будет разным ("в тикетах кнопки, в review хаос")
- Логика budget/active/passive дублируется
- Ответ пользователя иногда будет "уходить в никуда"
- Сложнее тестировать и дебажить

**Почему не "всегда LLM вопросы":**
- Потеряем детерминизм
- Потеряем воспроизводимость
- Потеряем контролируемое заполнение полей
- Потеряем кнопку-идемпотентность
- Снова получим "бот не понял"

**Итоговая формула:**
```
One Engine + Two Providers + Two Target States
= MARO ведущий в architecture review
+ MARO надёжный оператор для Jira
```

</specifics>

<notes>
## Additional Context

Phase 36 создал Question Engine для тикетов (QuestionCatalog, AnswerMapper, BudgetTracker). Phase 37 абстрагирует этот движок и добавляет второй провайдер.

Ключевой инсайт: review_continuation.py сейчас использует LLM напрямую для генерации вопросов. Нужно переключить на FreeformProvider → Question Engine, чтобы получить единый UX.

</notes>

---

*Phase: 37-unified-question-engine*
*Context gathered: 2026-01-24*
