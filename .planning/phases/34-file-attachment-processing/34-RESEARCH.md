# Phase 34: File Attachment Processing - Research

**Researched:** 2026-01-24
**Domain:** Document extraction, chunking, retrieval (RAG)
**Confidence:** HIGH (internal codebase audit)

<research_summary>
## Summary

Audited existing document processing infrastructure. The project has **40% of required components ready to use** — text extraction and Slack file download work. The remaining 60% needs to be built: event handling, storage, chunking, embeddings, retrieval.

**Key finding:** Don't build custom embedding/retrieval. Extend existing Zep integration OR use pgvector with PostgreSQL already in place.

**Primary recommendation:** Leverage existing `src/documents/` utilities, extend Zep for document storage, add chunking with LangChain text splitters.
</research_summary>

<existing_infrastructure>
## What Already Exists

### Text Extraction — READY
**Location:** `src/documents/extractor.py`

| Function | Purpose |
|----------|---------|
| `extract_pdf(content: bytes)` | PDF via pypdf, joins pages |
| `extract_docx(content: bytes)` | DOCX via python-docx, strips formatting |
| `extract_text(content: bytes, encoding)` | Plain text with UTF-8 fallback |
| `extract_from_file(content, filename)` | Auto-detect format by extension |
| `normalize_for_llm(text, max_length=10000)` | Clean whitespace, truncate with marker |

**Supported formats:** PDF, DOCX, TXT, MD

### Slack File Download — READY
**Location:** `src/documents/slack.py`

| Function | Purpose |
|----------|---------|
| `download_and_extract(client, file_info, max_length)` | Download + extract in one call |
| `get_extractable_files(files: list)` | Filter to supported MIME types |

**Supported MIME types:**
- `application/pdf`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `text/plain`
- `text/markdown`

### Zep Memory — PARTIAL
**Location:** `src/memory/zep_client.py`

Currently stores epic/thread summaries. Has semantic search capability.
Can be extended for document storage.

### LangChain — READY
**Location:** `pyproject.toml`

```
langchain-core
langchain-anthropic>=0.2
langchain-openai>=0.2
langchain-google-genai
```

Can use for: text splitters, embedding generation, RAG chains.

### Database — READY (schema missing)
PostgreSQL with async support (psycopg). Store pattern established.
Need to add document tables.
</existing_infrastructure>

<missing_components>
## What's Missing

### 1. File Event Handling
**Location:** `src/slack/router.py`
**Gap:** No `file_shared` event handler, no `files` array processing in messages

**Current handlers:**
- ✓ `app_mention`
- ✓ `message` (text only)
- ✗ `file_shared` — NOT REGISTERED

### 2. Document Storage
**Gap:** No database schema for documents

**Required tables:**
```sql
-- Attachment metadata
CREATE TABLE attachments (
    id UUID PRIMARY KEY,
    channel_id TEXT NOT NULL,
    thread_ts TEXT,
    file_id TEXT NOT NULL,  -- Slack file ID
    filename TEXT NOT NULL,
    mimetype TEXT NOT NULL,
    size_bytes INTEGER,
    extracted_text TEXT,
    summary TEXT,  -- 1-3 line auto-summary
    status TEXT DEFAULT 'pending',  -- pending, ready, failed, too_large
    pinned BOOLEAN DEFAULT FALSE,
    uploaded_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(file_id)
);

-- Chunks for retrieval
CREATE TABLE attachment_chunks (
    id UUID PRIMARY KEY,
    attachment_id UUID REFERENCES attachments(id),
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Link to WorkItems/Decisions
CREATE TABLE attachment_links (
    id UUID PRIMARY KEY,
    attachment_id UUID REFERENCES attachments(id),
    entity_type TEXT NOT NULL,  -- workitem, decision
    entity_id UUID NOT NULL,
    link_type TEXT DEFAULT 'context',  -- context, source, reference
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(attachment_id, entity_type, entity_id)
);
```

### 3. Chunking Strategy
**Gap:** No text splitting for context windows

**Recommendation:** Use LangChain `RecursiveCharacterTextSplitter`:
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,  # ~500 tokens
    chunk_overlap=50,
    separators=["\n\n", "\n", ". ", " "]
)
chunks = splitter.split_text(extracted_text)
```

### 4. Retrieval Pipeline
**Gap:** No semantic search over document content

**Options:**
1. **Extend Zep** — Already has embeddings, add document collection
2. **pgvector** — PostgreSQL extension, keeps everything in one DB
3. **Full-text search** — PostgreSQL tsvector, simpler but less semantic

**Recommendation:** Start with PostgreSQL full-text search (simpler), add embeddings later if needed.

### 5. Pin/Unpin Mechanics
**Gap:** No UI or state management for pinned attachments

**Required:**
- `[Pin as context]` button on attachment messages
- Store `pinned` flag in attachments table
- Show pinned files in thread status
- Include pinned in BUILD/THINK, exclude from CHAT
</missing_components>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── documents/
│   ├── __init__.py
│   ├── extractor.py      # ✓ EXISTS
│   ├── slack.py          # ✓ EXISTS
│   ├── chunker.py        # NEW: text splitting
│   └── retriever.py      # NEW: search/retrieval
├── db/
│   ├── attachment_store.py  # NEW: CRUD for attachments
│   └── models.py            # ADD: Attachment, AttachmentChunk
├── slack/
│   ├── handlers/
│   │   └── attachments.py   # NEW: file event handlers
│   └── blocks/
│       └── attachments.py   # NEW: attachment UI blocks
```

### Pattern 1: Attachment as First-Class Entity
**What:** Each file becomes an Attachment record with lifecycle
**When:** Always — files are objects, not inline text

```python
class Attachment(BaseModel):
    id: UUID
    file_id: str  # Slack file ID
    filename: str
    mimetype: str
    extracted_text: Optional[str]
    summary: Optional[str]
    status: Literal["pending", "ready", "failed", "too_large"]
    pinned: bool = False
    channel_id: str
    thread_ts: Optional[str]
    uploaded_by: str
```

### Pattern 2: Intent-Scoped Inclusion
**What:** Different intents get different attachment policies
**When:** Always — prevents context pollution

```python
ATTACHMENT_POLICIES = {
    SuperMode.CHAT: "none",      # Don't include, offer to use
    SuperMode.THINK: "pinned+retrieval",  # Pinned auto + top-K chunks
    SuperMode.BUILD: "pinned+structural", # Pinned auto + requirements/AC
    SuperMode.OPERATE: "logs_only",       # Only logs/stacktraces
    SuperMode.DECIDE: "pinned+cited",     # Pinned + source citations
}
```

### Pattern 3: Retrieval-Based Inclusion
**What:** Use top-K chunks, not whole document
**When:** Document > 1000 tokens

```python
async def get_relevant_chunks(
    attachment_id: UUID,
    query: str,
    top_k: int = 5
) -> list[str]:
    # Full-text search or embedding similarity
    chunks = await attachment_store.search_chunks(
        attachment_id=attachment_id,
        query=query,
        limit=top_k
    )
    return [c.chunk_text for c in chunks]
```

### Anti-Patterns to Avoid
- **Including whole file in prompt** — Kills context, degrades quality
- **Auto-including all attachments** — Token garbage collector
- **No transparency** — User must see what was used
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF extraction | Custom parser | `pypdf` (already in project) | Edge cases, encodings, layouts |
| DOCX extraction | XML parsing | `python-docx` (already in project) | Complex format |
| Text splitting | Simple split | LangChain `RecursiveCharacterTextSplitter` | Handles boundaries properly |
| Embeddings | Custom vectors | Zep or OpenAI embeddings | Quality, speed, cost |
| Semantic search | Custom similarity | PostgreSQL full-text or Zep | Proven, optimized |

**Key insight:** Document processing has decades of solved problems. The extractors already work. Focus on integration, not reinventing.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Token Explosion
**What goes wrong:** Including whole documents fills context window
**Why it happens:** "Just include the file" seems simpler
**How to avoid:** Chunk + retrieve top-K, never include whole doc
**Warning signs:** LLM responses degrade, costs spike

### Pitfall 2: Silent Failures
**What goes wrong:** File extraction fails, user never knows
**Why it happens:** No status tracking, errors swallowed
**How to avoid:** Store status (pending/ready/failed), show in UI
**Warning signs:** "Bot ignored my file" complaints

### Pitfall 3: Context Pollution
**What goes wrong:** Irrelevant file content confuses LLM
**Why it happens:** Including attachments in CHAT mode
**How to avoid:** Intent-scoped policies, only include when relevant
**Warning signs:** Bot answers based on wrong context

### Pitfall 4: No Transparency
**What goes wrong:** User doesn't know what file content was used
**Why it happens:** No "Used: filename (sections)" feedback
**How to avoid:** Always show `📎 Used: X (sections: Y, Z)`
**Warning signs:** User loses trust, can't verify bot's reasoning
</common_pitfalls>

<implementation_order>
## Implementation Order

### Wave 1: Foundation (Parallel)
- **34-01:** Attachment schema + AttachmentStore
- **34-02:** File event handler (`file_shared`, message `files` array)

### Wave 2: Processing (Parallel)
- **34-03:** Extraction pipeline (download → extract → store → summarize)
- **34-04:** Chunking + full-text search index

### Wave 3: Integration
- **34-05:** Pin/Unpin mechanics + UI buttons
- **34-06:** Intent-scoped inclusion rules

### Wave 4: Polish
- **34-07:** Transparency UI (`📎 Used: ...`, `[Show sources]`)
- **34-08:** Retrieval-based context injection
</implementation_order>

<code_examples>
## Code Examples

### Existing: Extract from Slack file
```python
# Source: src/documents/slack.py
from src.documents.slack import download_and_extract

async def process_file(client: WebClient, file_info: dict) -> Optional[str]:
    text = await download_and_extract(client, file_info, max_length=10000)
    return text
```

### Existing: Normalize for LLM
```python
# Source: src/documents/extractor.py
from src.documents.extractor import normalize_for_llm

clean_text = normalize_for_llm(raw_text, max_length=10000)
# Removes excess whitespace, truncates with "[Document truncated...]"
```

### New: Chunking with LangChain
```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

def chunk_document(text: str, chunk_size: int = 500) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=50,
        separators=["\n\n", "\n", ". ", " "]
    )
    return splitter.split_text(text)
```

### New: Full-text search (PostgreSQL)
```sql
-- Add search column
ALTER TABLE attachment_chunks ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED;

CREATE INDEX idx_chunks_search ON attachment_chunks USING GIN(search_vector);

-- Search query
SELECT chunk_text, ts_rank(search_vector, query) as rank
FROM attachment_chunks, plainto_tsquery('english', $1) query
WHERE search_vector @@ query
ORDER BY rank DESC
LIMIT 5;
```
</code_examples>

<sources>
## Sources

### Primary (HIGH confidence)
- `src/documents/extractor.py` — Verified working extraction
- `src/documents/slack.py` — Verified working download
- `src/memory/zep_client.py` — Existing Zep integration
- `pyproject.toml` — Verified dependencies

### Secondary (MEDIUM confidence)
- LangChain text splitters — Well-documented, stable API
- PostgreSQL full-text search — Native feature, no additional deps

### Tertiary (needs validation)
- Zep document extension — May need version check
- pgvector — Not currently installed, would need to add
</sources>

<metadata>
## Metadata

**Research scope:**
- Core: Document extraction (existing)
- Ecosystem: LangChain chunking, PostgreSQL search
- Patterns: Attachment entity, intent-scoped inclusion
- Pitfalls: Token explosion, silent failures, no transparency

**Confidence breakdown:**
- Existing code: HIGH — Audited directly
- Architecture: HIGH — Based on 34-CONTEXT.md vision
- Chunking/retrieval: MEDIUM — Standard patterns, needs validation
- Zep extension: MEDIUM — Needs testing

**Research date:** 2026-01-24
**Valid until:** N/A (internal audit)
</metadata>

---

*Phase: 34-file-attachment-processing*
*Research completed: 2026-01-24*
*Ready for planning: yes*
