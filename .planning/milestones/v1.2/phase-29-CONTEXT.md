# Phase 29: Sync on Demand — Context

> Vision captured from discussion session

---

## Core Concept

**Два компонента, разные цели:**

| Component | Purpose | Trigger |
|-----------|---------|---------|
| **Preflight Sync** | Автоматическая защита перед Jira операциями | Автоматически перед jira_create/update/transition |
| **/maro sync** | Диагностика и reconciliation | Ручная команда оператора |

---

## Preflight Sync — Safety Layer

### Философия

> Preflight — это не error handler.
> Это **согласователь состояний реальности**.

Как git conflict — это не ошибка, а **осознанное событие**, требующее человеческого решения.

**Принципы:**
- Никогда auto-write
- Никогда auto-fix
- Только: остановить → показать → ждать выбора

### Типы конфликтов

#### 1. Idempotent (Trivial)
*Операция уже выполнена вне MARO*

**Пример:** Хочешь перевести в Done → в Jira уже Done

**Поведение:**
```
ℹ️ SCRUM-163 is already Done in Jira.
Local state updated.
```

**Действие:** Операция считается успешной, локальный registry обновляется, никаких кнопок.

Это **optimistic idempotency**.

---

#### 2. Safe Drift
*Изменения есть, но не пересекаются с операцией*

**Пример:** Хочешь поменять label → в Jira кто-то поменял assignee

**Поведение:**
```
⚠️ SCRUM-163 was updated in Jira since last sync.
Fields changed: assignee.
Your operation affects: labels.

No overlap detected.
Proceed?
[Apply my change]  ← default
[Pull Jira changes only]
[Cancel]
```

---

#### 3. Real Conflict
*Пересекающиеся изменения*

**Пример:** Хочешь изменить description → в Jira description уже изменили

**Поведение:**
```
🚨 Conflict detected for SCRUM-163

Both Jira and Channel modified the same fields:
- Description

Jira version updated by @alex at 13:29
Channel version updated in this channel at 13:21

Choose how to resolve:
[Use Jira version]
[Use Channel version]
[Show diff]
[Cancel]
```

**Действие:** Операция приостановлена до выбора.

---

#### 4. Structural Conflict
*Невозможная операция*

**Пример:** Хочешь перевести в Done → тикет уже Cancelled

**Поведение:**
```
❌ Cannot apply operation.

SCRUM-163 is in status "Cancelled".
Transition to Done is not allowed.

Choose:
[Reopen issue]
[Cancel operation]
```

---

### Summary Table

| Тип | Что делать |
|-----|------------|
| Idempotent | Auto-success + sync |
| Safe drift | Ask, but default = proceed |
| Real conflict | Block + choice |
| Structural | Block + explanation |

---

## /maro sync — Diagnostic Command

### Цель

Операторская команда для reconciliation. Показывает полную картину расхождений между каналом и Jira.

### Секции отчёта

1. **Changed** — Jira отличается от локального кэша
2. **In sync** — Совпадают
3. **Missing locally** — Есть в Jira (child issues), но не отслеживаются
4. **Local only** — Отслеживаются, но нет в Jira (удалены?)

### Missing Locally — Важно!

> Registry = что канал **сознательно решил** отслеживать.

**Поведение:**
```
📋 Missing locally (3 issues)

These issues exist in Jira under tracked epics
but are not in this channel's registry:

SCRUM-170: Implement caching layer (Story)
SCRUM-171: Add rate limiting (Task)
SCRUM-172: Fix memory leak (Bug)

[Track all] [Track selected...] [Ignore]
```

**Не auto-add!** Предлагаем кнопки выбора.

Это как `git branch --track` — явное решение, что отслеживать.

---

## Ключевая философия

> "Ты буквально строишь distributed version control для смысла."

- **Communication as Source of Truth** — Jira это projection
- **Channel decides** — Registry хранит осознанный выбор
- **Never silent** — Каждое расхождение видимо
- **Human choice** — Автоматика только для идемпотентных случаев

---

## What's Essential for This Phase

1. **Preflight classification** — 4 типа конфликтов с разным UX
2. **Registry sync fields** — status, assignee, jira_updated, last_synced
3. **/maro sync report** — полная диагностика с action buttons
4. **No auto-decisions** — только inform + offer choices

---

## Out of Scope

- Jira webhooks (требует HTTP endpoint)
- Automatic periodic sync (cron)
- Two-way merge for real conflicts (пока только choose one)
- WorkItem sync (только registry)
