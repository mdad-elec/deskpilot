"""
Curated knowledge base — the assistant's source for how-to / process / policy answers.

Embeds your own documents (SOPs, workflows, training material) and stores
chunks + vectors in a JSON index on the sites volume, so it survives a container
recreate. `search_knowledge` runs a hybrid dense + BM25 search and returns the top
chunks WITH source attribution, so process answers are traceable to a document you
approved rather than to the model's memory.

Documents come from whichever source is configured in Deskpilot Settings (a Frappe
File folder or a Google Drive folder); see kb_files.py and kb_drive.py.
"""

import collections
import json
import math
import os
import re
import threading
import urllib.request

import frappe

from deskpilot import config

CHUNK_CHARS = 2400
CHUNK_OVERLAP = 300

# Retrieval tuning. Hybrid = dense vectors ∪ BM25 keywords, fused with Reciprocal
# Rank Fusion. Dense alone misses exact tokens (field names, doctype names, codes
# like "222110"); BM25 alone misses paraphrase. RRF needs no score calibration
# between the two, which is why it is used instead of a weighted sum.
RRF_K = 60
CANDIDATES = 40          # per retriever, before fusion
BM25_K1 = 1.5
BM25_B = 0.75
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are",
    "how", "do", "i", "we", "what", "when", "which", "with", "that", "this",
    "it", "be", "can", "should", "does", "our", "my", "you", "your", "at", "by",
    "from", "as", "if", "not", "but", "so", "there", "then", "than", "into",
}

# EMBEDDINGS ARE A SEPARATE ENDPOINT FROM CHAT.
# These two once shared one base URL. When the chat endpoint was later pointed at a
# server that hosts only a chat model, every embedding call started 404-ing — and the
# exception was swallowed, so the whole local index silently went dark for months
# while answers came from elsewhere. Keep the two independent, and fail LOUDLY
# (see search_knowledge). The defaults below are a stock local Ollama.
DEFAULT_EMBED_BASE = "http://127.0.0.1:11434/v1"
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Optional federated knowledge layer: an MCP endpoint exposing a search tool, so a
# KB maintained outside this site can be queried alongside the local index.
# Configured in Deskpilot Settings; blank = off.
KB_MCP_TOOL = "kb-search"


def _kb_path():
    return os.path.join(frappe.get_site_path("private", "files"), "deskpilot_kb.json")


def _vec_path():
    """Vectors live in a numpy sidecar, not inside the JSON.

    Keeping 768 floats per chunk inline meant _load() re-read and re-parsed a
    5.6 MB JSON on EVERY query (measured 0.118s) and scoring was a pure-python
    loop (0.069s) — both linear in corpus size, so a 10x bigger KB would have
    cost ~2s per question. A float32 matrix is memory-mapped once and scored with
    a single dot product.
    """
    return os.path.join(frappe.get_site_path("private", "files"),
                        "deskpilot_kb_vectors.npy")


# process-local index cache, invalidated by file mtime
_IDX = {}
_IDX_LOCK = threading.Lock()


def _tokens(text):
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower())
            if len(t) > 1 and t not in STOPWORDS]


def _build_keyword_index(chunks):
    """Postings + idf for BM25. Built once per index load, not per query."""
    postings, lengths = {}, []
    for i, c in enumerate(chunks):
        toks = _tokens(_chunk_blob(c))
        lengths.append(len(toks) or 1)
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t, n in tf.items():
            postings.setdefault(t, []).append((i, n))
    n = len(chunks) or 1
    idf = {t: math.log(1 + (n - len(pl) + 0.5) / (len(pl) + 0.5))
           for t, pl in postings.items()}
    return {"postings": postings, "idf": idf, "lengths": lengths,
            "avglen": (sum(lengths) / float(n)) if lengths else 1.0}


def _chunk_blob(c):
    """What gets indexed/embedded: title and heading carry real signal."""
    parts = [c.get("title") or "", c.get("heading") or "", c.get("text") or ""]
    return "\n".join(p for p in parts if p)


def _index():
    """Load (and cache) the chunk metadata, vector matrix and keyword index."""
    import numpy as np
    kp, vp = _kb_path(), _vec_path()
    try:
        kmt = os.path.getmtime(kp)
    except OSError:
        return None
    vmt = os.path.getmtime(vp) if os.path.exists(vp) else 0
    cached = _IDX.get("key")
    if cached == (kp, kmt, vmt) and _IDX.get("chunks") is not None:
        return _IDX
    with _IDX_LOCK:
        if _IDX.get("key") == (kp, kmt, vmt) and _IDX.get("chunks") is not None:
            return _IDX
        store = _migrate_if_needed()
        chunks = store.get("chunks") or []
        M = None
        if chunks and os.path.exists(vp):
            try:
                M = np.load(vp, mmap_mode="r")
                if M.shape[0] != len(chunks):
                    frappe.log_error(
                        "KB vector matrix has %d rows for %d chunks — run "
                        "deskpilot.kb.reembed()" % (M.shape[0], len(chunks)),
                        "deskpilot kb")
                    M = None
            except Exception:
                frappe.log_error(frappe.get_traceback(), "deskpilot kb vectors")
                M = None
        _IDX.clear()
        _IDX.update({"key": (kp, kmt, os.path.getmtime(vp) if os.path.exists(vp) else 0),
                     "chunks": chunks, "M": M, "docs": store.get("docs") or {},
                     "embed_model": store.get("embed_model"), "dim": store.get("dim"),
                     "kw": _build_keyword_index(chunks) if chunks else None})
        return _IDX


def _write_vectors(vectors):
    """Store L2-normalised float32 rows so cosine is a plain dot product."""
    import numpy as np
    M = np.asarray(vectors, dtype="float32")
    norms = np.linalg.norm(M, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    np.save(_vec_path(), M / norms)


def _migrate_if_needed():
    """v1 stored vectors inline in the JSON; move them to the sidecar once."""
    store = _load()
    if store.get("chunks") and "vector" in (store["chunks"][0] or {}):
        vectors = [c.pop("vector", None) for c in store["chunks"]]
        vectors = [v for v in vectors if v]
        if len(vectors) == len(store["chunks"]):
            _write_vectors(vectors)
            store["dim"] = len(vectors[0])
            store["v"] = 2
            _save(store)
            frappe.logger("deskpilot").info(
                "KB migrated to v2: %d vectors moved to %s" % (len(vectors), _vec_path()))
    return store


def _embed_config():
    base = config.get("embed_base") or DEFAULT_EMBED_BASE
    model = config.get("embed_model") or DEFAULT_EMBED_MODEL
    # Ollama ignores the bearer token; a hosted endpoint needs a real one.
    key = (config.get_password("embed_key")
           or frappe.conf.get("nvidia_api_key")
           or "not-needed")
    return base, model, key


def _embed(texts, input_type):
    """Return list of vectors for the given texts. input_type: 'query' | 'passage'."""
    base, model, key = _embed_config()
    body = {
        "input": texts,
        "model": model,
        "encoding_format": "float",
        "truncate": "END",
    }
    if "nvidia" in base or "integrate.api" in base:
        body["input_type"] = input_type      # NVIDIA-specific; Ollama rejects it
    req = urllib.request.Request(
        base.rstrip("/") + "/embeddings",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    return [d["embedding"] for d in data["data"]]


HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+\S.*"                     # markdown heading
    r"|\d+(?:\.\d+)*[.)]?\s+\S.{0,90}"      # 1. / 2.3 numbered heading
    r"|[A-Z][A-Z0-9 &/()\-,'.]{4,80}"         # SHORT ALL-CAPS line
    r"|(?:Step|Phase|Section|Part)\s+\d+.{0,80})$")


BOLD_ONLY_RE = re.compile(r"^\*\*(.{2,90}?)\*\*:?$")


def _heading_text(line):
    """Return the heading text if this line is a heading, else None.

    Google Docs' markdown export renders these SOPs' headings as **bold lines**
    rather than "# Heading", because the authors style them bold instead of using
    Heading styles. Treating a wholly-bold short line as a heading is what makes
    the structure usable — without it these documents chunk as one flat wall.
    """
    line = (line or "").strip()
    if not line or len(line) > 100:
        return None
    m = BOLD_ONLY_RE.match(line)
    if m:
        return m.group(1).strip()
    if line.endswith((".", ";")) and not line.startswith("#"):
        return None                # a sentence, not a heading
    if HEADING_RE.match(line):
        return line.lstrip("#").strip()
    return None


def _looks_like_heading(line):
    return _heading_text(line) is not None


def _chunk(text):
    """Split into (heading, body) chunks.

    Splitting on headings first keeps a procedure's steps together instead of
    cutting mid-procedure at an arbitrary character count, and the heading is
    carried into the embedded/indexed text so "expense claim approval" matches the
    section that is actually about approval.
    """
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        return []
    sections, cur_h, cur = [], "", []
    for line in text.split("\n"):
        h = _heading_text(line)
        if h:
            if cur and "".join(cur).strip():
                sections.append((cur_h, "\n".join(cur).strip()))
            cur_h = h
            cur = []
        else:
            cur.append(line)
    if cur and "".join(cur).strip():
        sections.append((cur_h, "\n".join(cur).strip()))
    if not sections:
        sections = [("", text)]

    out = []
    for heading, body in sections:
        if len(body) <= CHUNK_CHARS:
            out.append({"heading": heading, "text": body})
            continue
        i, n = 0, len(body)
        while i < n:                      # long section: fall back to size split
            end = min(i + CHUNK_CHARS, n)
            if end < n:
                brk = body.rfind("\n\n", i + CHUNK_CHARS - 600, end)
                if brk == -1:
                    brk = body.rfind(". ", i + CHUNK_CHARS - 400, end)
                if brk > i:
                    end = brk
            piece = body[i:end].strip()
            if piece:
                out.append({"heading": heading, "text": piece})
            if end >= n:
                break
            i = max(end - CHUNK_OVERLAP, i + 1)
    return [c for c in out if c["text"]]


def _load():
    p = _kb_path()
    if os.path.exists(p):
        with open(p) as f:
            store = json.load(f)
        store.setdefault("docs", {})
        store.setdefault("chunks", [])
        return store
    return {"docs": {}, "chunks": [], "embed_model": None, "dim": None}


def _save(store):
    with open(_kb_path(), "w") as f:
        json.dump(store, f)


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------- ingestion

def ingest_text(source, title, text, replace=True):
    """Chunk + embed a document and add it to the KB. `source` is a stable id
    (e.g. drive file id or filename); re-ingesting the same source replaces it."""
    store = _load()
    _strip_inline_vectors(store)
    old_vectors = _existing_vectors(store)
    if replace:
        keep = [i for i, c in enumerate(store["chunks"]) if c.get("source") != source]
        store["chunks"] = [store["chunks"][i] for i in keep]
        old_vectors = [old_vectors[i] for i in keep] if old_vectors else []

    pieces = _chunk(text)
    if not pieces:
        store["docs"].pop(source, None)
        _save(store)
        if old_vectors:
            _write_vectors(old_vectors)
        return {"source": source, "chunks": 0}

    new_chunks = [{"source": source, "title": title, "idx": i,
                   "heading": p["heading"], "text": p["text"]}
                  for i, p in enumerate(pieces)]
    vectors = []
    B = 32
    blobs = [_chunk_blob(c) for c in new_chunks]
    for i in range(0, len(blobs), B):
        vectors.extend(_embed(blobs[i:i + B], "passage"))

    store["chunks"].extend(new_chunks)
    all_vectors = (old_vectors or []) + vectors
    _, model, _key = _embed_config()
    store["embed_model"] = model
    store["dim"] = len(vectors[0]) if vectors else store.get("dim")
    store["docs"][source] = {"title": title, "chunks": len(pieces)}
    store["v"] = 2
    _save(store)
    _write_vectors(all_vectors)
    _IDX.clear()
    return {"source": source, "title": title, "chunks": len(pieces)}


def _strip_inline_vectors(store):
    for c in store.get("chunks") or []:
        c.pop("vector", None)


def _existing_vectors(store):
    """Current sidecar rows as a list, or [] when there is no usable matrix."""
    import numpy as np
    vp = _vec_path()
    if not os.path.exists(vp):
        return []
    try:
        M = np.load(vp)
    except Exception:
        return []
    if M.shape[0] != len(store.get("chunks") or []):
        return []
    return [row for row in M]


def reembed(batch=32):
    """Re-embed every stored chunk with the CURRENTLY configured embed model.

    Chunk text is already in the store, so this needs no source files and no
    external key. Also upgrades older chunks to the title+heading-prefixed blob,
    which is what makes headings searchable.
    """
    store = _load()
    _strip_inline_vectors(store)
    chunks = store.get("chunks") or []
    if not chunks:
        return {"error": "KB is empty — nothing to re-embed."}
    base, model, _key = _embed_config()
    blobs = [_chunk_blob(c) for c in chunks]
    vectors = []
    for i in range(0, len(blobs), batch):
        vectors.extend(_embed(blobs[i:i + batch], "passage"))
    if len(vectors) != len(chunks):
        return {"error": "Embedding returned %d vectors for %d chunks — aborted."
                         % (len(vectors), len(chunks))}
    store["embed_model"] = model
    store["dim"] = len(vectors[0])
    store["v"] = 2
    _save(store)
    _write_vectors(vectors)
    _IDX.clear()
    return {"reembedded": len(chunks), "model": model, "base": base,
            "dim": store["dim"], "docs": len(store.get("docs", {}))}


# ----------------------------------------------------------------- retrieval

def _search_shared_kb(query, k):
    """Query the optional federated KB over MCP. Best-effort: never raises."""
    url = (config.get("kb_mcp_url", "") or "").strip()
    if not url:
        return []                      # not configured = feature off
    tok = config.get_password("kb_mcp_token")
    if not tok:
        frappe.log_error("A shared KB URL is set but its token is not — federated "
                         "search is disabled.", "deskpilot kb")
        return []
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": KB_MCP_TOOL,
                                  "arguments": {"query": query, "max_results": k}}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + tok, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8").strip()
        if not raw.startswith("{"):  # SSE-wrapped: pull the data: {...} line
            for line in raw.splitlines():
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    break
        payload = json.loads(raw)
        text = payload["result"]["content"][0]["text"]
        hits = json.loads(text).get("hits", [])
        out = []
        for h in hits[:k]:
            p = h.get("payload", {})
            title = p.get("title") or "Shared KB"
            out.append({"title": title, "source": "shared_kb:" + title,
                        "score": round(h.get("score", 0), 4),
                        "text": p.get("data") or p.get("text") or "", "origin": "shared_kb"})
        return out
    except Exception:
        return []


def _dense(qv, idx, limit):
    """Top-`limit` chunk ids by cosine, as one matrix-vector product."""
    import numpy as np
    M = idx.get("M")
    if M is None:
        return []
    q = np.asarray(qv, dtype="float32")
    n = float(np.linalg.norm(q)) or 1.0
    scores = np.asarray(M @ (q / n))
    if scores.size == 0:
        return []
    take = min(limit, scores.size)
    top = np.argpartition(-scores, take - 1)[:take]
    top = top[np.argsort(-scores[top])]
    return [(int(i), float(scores[i])) for i in top]


def _bm25(query, idx, limit):
    """Keyword ranking — catches exact tokens the embedding blurs away."""
    kw = idx.get("kw")
    if not kw:
        return []
    terms = _tokens(query)
    if not terms:
        return []
    scores = {}
    for t in set(terms):
        pl = kw["postings"].get(t)
        if not pl:
            continue
        idf = kw["idf"].get(t, 0.0)
        for i, tf in pl:
            dl = kw["lengths"][i]
            denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / kw["avglen"])
            scores[i] = scores.get(i, 0.0) + idf * (tf * (BM25_K1 + 1)) / (denom or 1.0)
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [(int(i), float(sc)) for i, sc in ranked]


def _fuse(dense, sparse, k=RRF_K):
    """Reciprocal Rank Fusion: combines two rankings without having to calibrate
    their score scales against each other."""
    fused = {}
    for rank, (i, sc) in enumerate(dense):
        e = fused.setdefault(i, {"rrf": 0.0, "vec": None, "kw": None})
        e["rrf"] += 1.0 / (k + rank + 1)
        e["vec"] = sc
    for rank, (i, sc) in enumerate(sparse):
        e = fused.setdefault(i, {"rrf": 0.0, "vec": None, "kw": None})
        e["rrf"] += 1.0 / (k + rank + 1)
        e["kw"] = sc
    return sorted(fused.items(), key=lambda x: x[1]["rrf"], reverse=True)


def search_local(query, k=5):
    """Hybrid local retrieval. Returns (hits, error_or_None)."""
    idx = _index()
    if not idx or not idx.get("chunks"):
        return [], None
    try:
        qv = _embed([query], "query")[0]
    except Exception as e:
        # FAIL LOUDLY. A silently-empty local KB hid for months.
        msg = str(e)[:200]
        frappe.log_error("copilot local KB embed failed: %s" % msg, "deskpilot kb")
        qv = None

    dense = []
    if qv is not None:
        M = idx.get("M")
        if M is not None and M.shape[1] != len(qv):
            msg = ("KB embedded with %s (dim %s) but the query model returns dim %d — "
                   "run deskpilot.kb.reembed()"
                   % (idx.get("embed_model"), idx.get("dim"), len(qv)))
            frappe.log_error(msg, "deskpilot kb")
            return [], msg
        dense = _dense(qv, idx, CANDIDATES)
    sparse = _bm25(query, idx, CANDIDATES)
    if not dense and not sparse:
        return [], ("embedding unavailable and no keyword match" if qv is None else None)

    chunks = idx["chunks"]
    out = []
    for i, meta in _fuse(dense, sparse)[:k]:
        c = chunks[i]
        out.append({
            "title": c.get("title"), "source": c.get("source"),
            "heading": c.get("heading") or "",
            "score": round(meta["rrf"], 6),
            "vector_score": round(meta["vec"], 4) if meta["vec"] is not None else None,
            "keyword_score": round(meta["kw"], 3) if meta["kw"] is not None else None,
            "matched": ("both" if meta["vec"] is not None and meta["kw"] is not None
                        else "vector" if meta["vec"] is not None else "keyword"),
            "text": c.get("text"), "origin": "erp_local",
        })
    return out, (None if qv is not None else "embedding endpoint unavailable")


# Chunks shorter than this are not knowledge. In practice a large share of retrieved
# chunks can be micro-fragments — a stray date, a one-line total — which rank on a
# single matching term and displace real answers. Worse, a fragment carrying a
# figure can surface it in reply to an entirely unrelated question.
KB_MIN_CHARS = 150

# TOPIC FILTER — "Blocked topics" in Deskpilot Settings, one phrase per line.
#
# The KB is shared: every user who can reach the assistant can retrieve any indexed
# chunk. If your document set contains material that is need-to-know (security
# reports, HR cases, anything under a restricted classification), indexing it makes
# it answerable to everyone. List phrases here and matching chunks are never
# returned.
#
# Matched against BOTH title and body, with separators collapsed first. Title-only
# matching is not enough: the same document is often indexed under several titles,
# and chunk titles are not reliably descriptive. Separator collapsing is not
# cosmetic — a real filename like "Security_Incident_Report.pdf" does not contain
# the substring "security incident" until the underscores are normalised away.
#
# Empty by default: this app ships no opinion about what your documents contain.
KB_DENY_PATTERNS = ()


def _deny_patterns():
    """Blocked topics from Settings, plus anything a site pinned in code."""
    return list(KB_DENY_PATTERNS) + [p.lower() for p in config.get_lines("blocked_topics")]


# DOCUMENT FILTER — "Excluded documents" in Deskpilot Settings, one phrase per line.
#
# Matched on TITLE/SOURCE ONLY, never on body text: matching the body would drop
# every chunk that merely mentions the document.
#
# What this is for: a large document that matches almost any query will crowd out
# the specific answer. A corpus where general corporate material outnumbers
# task-level material several to one will answer "how do I create a sales order"
# with a strategy deck. Name those documents here to keep them out of this
# assistant's retrieval without removing them from your document store.
#
# Empty by default.
KB_DOC_DENY = ()


def _doc_deny():
    """Excluded documents from Settings, plus anything a site pinned in code."""
    return list(KB_DOC_DENY) + [p.lower() for p in config.get_lines("excluded_documents")]


def _kb_doc_denied(title, source=""):
    hay = re.sub(r"[^a-z0-9]+", " ", (str(title or "") + " " + str(source or "")).lower())
    return any(re.sub(r"[^a-z0-9]+", " ", p) in hay for p in _doc_deny())


def _kb_excluded(row):
    """(drop?, why) for one retrieved chunk."""
    text = str(row.get("text") or "")
    title = str(row.get("title") or "")
    if _kb_doc_denied(title, row.get("source")):
        return True, "out_of_scope"
    # Collapse separators before matching, so a phrase written with spaces still
    # matches a filename that uses underscores or hyphens. Without this a pattern
    # never matches the document it was written for — caught by the regression
    # pin, not by reading the code.
    hay = re.sub(r"[^a-z0-9]+", " ", (title + " " + text).lower())
    for pat in _deny_patterns():
        if re.sub(r"[^a-z0-9]+", " ", pat) in hay:
            return True, "restricted:" + pat
    # The floor exists for the SHARED corpus, whose micro-fragments ("Report date:
    # 2026-08-03") rank on one term and crowd out real answers. Local curated docs are
    # deliberately exempt: their short chunks are section headers of documents written
    # for this purpose, and dropping them cost us the very content added to fix the gap.
    if str(row.get("origin") or "") != "erp_local" and len(text.strip()) < KB_MIN_CHARS:
        return True, "too_short"
    return False, None


@frappe.whitelist()
def search_knowledge(query, k=5):
    """Top-k KB chunks: hybrid local retrieval ∪ the optional shared KB."""
    from deskpilot.api import _guard_access
    _guard_access()          # whitelisted: exposes KB content to any Desk user
    k = int(k)
    local, local_error = search_local(query, k)
    shared = _search_shared_kb(query, k)

    # Merge and dedupe by normalised title, preferring the better-ranked entry.
    # Local hits are ranked by RRF and shared ones by the MCP's own score, which
    # are not comparable, so interleave instead of sorting one list.
    # Chunks per document. One was right when the corpus was a handful of sprawling
    # documents that would crowd each other out; it is wrong now that the ERP content is
    # curated one document per doctype. Measured 2026-08-21: "how do I create a sales
    # order" returned the "Opening it" section and discarded the mandatory-fields section
    # of the SAME document as a duplicate — the chunk that actually answered the question.
    PER_TITLE = 3
    merged, seen, dropped = [], collections.Counter(), []
    for r in _interleave(local, shared):
        key = re.sub(r"[^a-z0-9]", "", (r.get("title") or "").lower())[:40]
        if seen[key] >= PER_TITLE:
            continue
        # Filter BEFORE claiming the dedupe slot. Reversed, a document whose
        # first-ranked chunk was short got blacklisted outright: measured 2026-08-21,
        # a 147-character chunk of "How to: Sales Order" was dropped as too short and
        # the 253/480/665-character chunks behind it were then skipped as duplicates,
        # so the one document that answered the question never surfaced.
        skip, why = _kb_excluded(r)
        if skip:
            dropped.append((str(r.get("title") or "?")[:60], why))
            continue
        seen[key] += 1
        merged.append(r)
    if dropped:
        try:
            from deskpilot.api import _log
            _log({"type": "kb_filtered", "query": str(query)[:80],
                  "dropped": [{"title": t, "why": w} for t, w in dropped[:6]]})
        except Exception:
            pass
    out = merged[:k]
    sources = sorted({r["origin"] for r in out})
    if local_error:
        sources.append("local_kb_error")
    res = {
        "results": out,
        "sources_used": sources,
        # Chunks from several documents come back together and the model has been
        # observed quoting one document while citing another's title. Spell out the
        # rule in the tool result, where it is adjacent to the evidence.
        "citation_rule": ("Cite the `title` of the specific chunk you used. Do not "
                          "attribute text from one title to another, and do not merge "
                          "titles. If you use two chunks with different titles, cite both."),
    }
    if local_error:
        res["local_kb_error"] = local_error
    return res


def _interleave(a, b):
    """Round-robin two ranked lists so neither source can crowd the other out."""
    out, i = [], 0
    while i < max(len(a), len(b)):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
        i += 1
    return out


def ingest_dir(path, mapping):
    """Ingest each file named in `mapping` (filename -> citation title) from `path`."""
    if isinstance(mapping, str):
        mapping = json.loads(mapping)
    results = []
    for fn, title in mapping.items():
        full = os.path.join(path, fn)
        if not os.path.isfile(full):
            results.append({"source": fn, "error": "not found"})
            continue
        with open(full, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        results.append(ingest_text(fn, title, text))
    return results


def reset_kb():
    """Wipe the KB store (e.g. before a clean re-ingest)."""
    _save({"docs": {}, "chunks": [], "embed_model": None, "dim": None, "v": 2})
    try:
        os.remove(_vec_path())
    except OSError:
        pass
    _IDX.clear()
    return {"ok": True}


@frappe.whitelist()
def kb_stats():
    from deskpilot.api import _guard_access
    _guard_access()
    idx = _index() or {}
    base, model, _key = _embed_config()
    M = idx.get("M")
    return {
        "docs": idx.get("docs") or {},
        "total_chunks": len(idx.get("chunks") or []),
        "stored_embed_model": idx.get("embed_model"), "stored_dim": idx.get("dim"),
        "configured_embed_model": model, "configured_embed_base": base,
        "vectors": ("%dx%d" % (M.shape[0], M.shape[1])) if M is not None else "MISSING",
        "keyword_terms": len((idx.get("kw") or {}).get("postings") or {}),
        "shared_kb_configured": bool((config.get("kb_mcp_url", "") or "").strip()),
    }
