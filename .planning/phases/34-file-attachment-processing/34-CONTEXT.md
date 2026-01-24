# Phase 34: File Attachment Processing - Context

**Gathered:** 2026-01-24
**Status:** Ready for planning

<vision>
## How This Should Work

Attachments are dangerous — they're heavy, sticky, and easily "clog the model's brain." But they often contain the most important information. So the approach must be policy-based hybrid: deterministic rules + LLM for selecting relevant chunks.

**Core Model:**

1. **Attachment = First-Class Object** (not just text in history)
   ```
   Attachment {
     id, thread_ts, uploaded_by
     filename, mime_type, size
     extracted_text (optional)
     summary (short, 1-3 lines)
     embeddings_ref (optional)
     status: READY | FAILED | TOO_LARGE
   }
   ```
   Available through retrieval, not always in prompt.

2. **Two Usage Modes:**

   **A) Pinned Attachments (Active)**
   - User or MARO can "pin to context" via button or `/maro attach pin <file>`
   - Pinned = automatically used in BUILD/THINK, but not in CHAT
   - Visible in status: `Context: • Pinned: spec.pdf, api_contract.md`

   **B) On-Demand Attachments**
   - Used only if user explicitly references ("in this document", "in attachment")
   - Or if intent requires AND retrieval shows high relevance

3. **Intent-Scoped Rules:**

   | Mode | Attachment Policy |
   |------|-------------------|
   | CHAT | Don't include. Offer: "I see an attachment, want me to use it?" |
   | THINK | Pinned auto + top-K chunks from unpinned if retrieval score high |
   | BUILD | Pinned auto + structural fragments (requirements, AC, constraints) |
   | OPERATE | Only logs, JSON payloads, stacktraces — via retrieval |
   | DECIDE | Pinned + cited chunks with source references |

4. **Never "include whole file"** — only chunks (300-800 tokens), top 3-6 per retrieval, plus auto-summary.

5. **Transparency UI:**
   ```
   📎 Used: spec.pdf (sections: Auth, Permissions)
   [Show sources] [Stop using this file]
   ```

</vision>

<essential>
## What Must Be Nailed

All pieces are equally critical — can't ship without the full pipeline:

1. **Attachment as entity** — Detect, register, extract text, generate summary
2. **Pin/Unpin control** — Explicit user control over what's in context
3. **Chunking + Retrieval** — 300-800 token chunks, vector store, top-K retrieval
4. **Intent-scoped rules** — Different policies for BUILD/THINK/CHAT/OPERATE/DECIDE
5. **Transparency** — Always show what files/sections were used

</essential>

<specifics>
## Specific Ideas

**Three Product Rules:**
1. Attachments are opt-in by default (not automatic)
2. Pinned attachments become part of object context
3. Everything else is retrieval-based and intent-scoped

**UI Elements:**
- `[Use as context]` / `[Pin as context]` button on attachments
- Status line showing pinned files
- `📎 Used: filename (sections: X, Y)` after responses
- `[Show sources]` to see cited chunks
- `[Stop using this file]` to unpin

**Key Principle:** Don't turn the system into a token garbage collector. Precision and control over "include everything."

</specifics>

<notes>
## Additional Context

Existing infrastructure in `src/documents/`:
- `extractor.py` — PDF/DOCX/TXT/Markdown extraction (pypdf, python-docx)
- `slack.py` — `download_and_extract()` for Slack file downloads

What's missing:
- Attachment entity/store
- Chunking pipeline
- Embeddings + vector store
- Retrieval integration
- Pin/unpin mechanics
- Intent-scoped inclusion rules
- Transparency UI

This is a significant phase — likely 6-8 plans covering the full pipeline from file detection to retrieval-augmented generation.

</notes>

---

*Phase: 34-file-attachment-processing*
*Context gathered: 2026-01-24*
