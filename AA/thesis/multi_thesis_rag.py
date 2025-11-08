import dotenv
dotenv.load_dotenv()


def recover_chromadb_from_index(pdf_folder, chunk_size=500):
    """
    If ChromaDB is empty but indexed_files.json exists, re-embed and re-index all PDFs listed in indexed_files.json.
    """
    indexed_path = os.path.join(pdf_folder, "indexed_files.json")
    if not os.path.exists(indexed_path):
        print("[RECOVERY] No indexed_files.json found. Skipping ChromaDB recovery.")
        return 0
    with open(indexed_path, "r", encoding="utf-8") as f:
        indexed_files = json.load(f)
    if not indexed_files:
        print("[RECOVERY] indexed_files.json is empty. Skipping ChromaDB recovery.")
        return 0
    embedder = SentenceTransformer('all-MiniLM-L6-v2')
    from extract_metadata import extract_thesis_metadata
    recovered_chunks = 0
    for txt_path in indexed_files:
        if not os.path.exists(txt_path):
            print(f"[RECOVERY] Missing .txt for {txt_path}, skipping.")
            continue
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()
        meta = extract_thesis_metadata(text)
        meta["file"] = os.path.basename(txt_path)  # Use .txt as the source
        meta["pdf"] = os.path.basename(txt_path)   # Use .txt as the 'pdf' reference
        meta["chunk_idx"] = 0  # Will be set per chunk
        # Ensure 'subjects' is always a string
        if "subjects" in meta and isinstance(meta["subjects"], list):
            meta["subjects"] = ", ".join(str(s) for s in meta["subjects"])
        # Ensure 'university' is present
        if "university" not in meta:
            meta["university"] = ""
        chunks = sentence_chunking(text, chunk_size=chunk_size)
        chunk_embeddings = embed_chunks(chunks, embedder)
        chunk_metadatas = []
        for idx, chunk in enumerate(chunks):
            meta_copy = dict(meta)
            meta_copy["chunk_idx"] = idx
            if "subjects" in meta_copy and isinstance(meta_copy["subjects"], list):
                meta_copy["subjects"] = ", ".join(str(s) for s in meta_copy["subjects"])
            for k, v in meta_copy.items():
                if v is None:
                    meta_copy[k] = ""
            # Ensure 'university' is present in each chunk
            if "university" not in meta_copy:
                meta_copy["university"] = ""
            chunk_metadatas.append(meta_copy)
        ids = [f"{os.path.basename(txt_path)}_chunk_{i}" for i in range(len(chunks))]
        collection.add(
            embeddings=[list(map(float, emb)) for emb in chunk_embeddings],
            documents=chunks,
            metadatas=chunk_metadatas,
            ids=ids
        )
        recovered_chunks += len(chunks)
        print(f"[RECOVERY] Re-indexed {os.path.basename(txt_path)} with {len(chunks)} chunks.")
    print(f"[RECOVERY] Total recovered chunks: {recovered_chunks}")
    return recovered_chunks
def embed_chunks(chunks, embedder):
    # Returns a numpy array of embeddings for all chunks
    return np.array(embedder.encode(chunks, show_progress_bar=True, convert_to_numpy=True))


def build_chromadb_index(chunks, chunk_embeddings, metadata):
    # Insert data into ChromaDB
    ids = [f"chunk_{i}" for i in range(len(chunks))]
    metadatas = []
    for m in metadata:
        subjects_val = m.get("subjects", [])
        if isinstance(subjects_val, list):
            subjects_str = ", ".join(subjects_val)
        else:
            subjects_str = str(subjects_val)
        metadatas.append({
            "file": m.get("file", m.get("pdf", "")),  # Use .txt as the source if available
            "title": m["title"],
            "author": m["author"],
            "publication_year": m["publication_year"],
            "chunk_idx": m["chunk_idx"],
            "degree": m.get("degree", "Thesis"),
            "call_no": m.get("call_no", ""),
            "subjects": subjects_str,
            "abstract": m.get("abstract", ""),
            "university": m.get("university", "")
        })
    collection.add(
        embeddings=[list(map(float, emb)) for emb in chunk_embeddings],
        documents=chunks,
        metadatas=metadatas,
        ids=ids
    )
    return collection


def search_chromadb(query, embedder, collection, top_n=10, distance_threshold=1.5):
    query_emb = embedder.encode([query], convert_to_numpy=True)[0].tolist()
    results = collection.query(
        query_embeddings=[query_emb],
        n_results=top_n,
        include=["documents", "metadatas", "distances"]
    )
    out = []
    print(f"\n[DEBUG] Top {top_n} results for query: '{query}'")
    # Collect top chunks, ensuring top 5 unique txt files are represented
    seen_files = set()
    unique_chunks = []
    for i in range(len(results["documents"][0])):
        meta = results["metadatas"][0][i]
        score = float(results["distances"][0][i])
        print(f"  Rank {i+1}: Score={score:.4f}, Title={meta.get('title','')}, Author={meta.get('author','')}, Year={meta.get('publication_year','')}")
        # Only include if score is below threshold (Euclidean: lower is better)
        if score < distance_threshold:
            file_id = meta.get("file") or meta.get("pdf")
            if file_id and file_id not in seen_files:
                unique_chunks.append({
                    "chunk": results["documents"][0][i],
                    "meta": meta,
                    "score": score
                })
                seen_files.add(file_id)
            if len(unique_chunks) >= 5:
                break
    # If fewer than 5 unique, fill up to top_n with best scoring chunks (may repeat files)
    if len(unique_chunks) < 5:
        for i in range(len(results["documents"][0])):
            meta = results["metadatas"][0][i]
            score = float(results["distances"][0][i])
            if score < distance_threshold:
                file_id = meta.get("file") or meta.get("pdf")
                # Allow repeats if not already in unique_chunks
                if not any(c["chunk"] == results["documents"][0][i] for c in unique_chunks):
                    unique_chunks.append({
                        "chunk": results["documents"][0][i],
                        "meta": meta,
                        "score": score
                    })
            if len(unique_chunks) >= top_n:
                break
    return unique_chunks

def sentence_chunking(text, chunk_size=500):
    # Sliding window chunking with overlap
    sentences = text.split('. ')
    # Re-add the period lost in split
    sentences = [s.strip() + ('' if s.strip().endswith('.') else '.') for s in sentences if s.strip()]
    chunks = []
    window = []
    window_len = 0
    overlap = int(chunk_size * 0.2)  # 20% overlap by word count
    i = 0
    while i < len(sentences):
        window = []
        window_len = 0
        j = i
        while j < len(sentences) and window_len < chunk_size:
            sent = sentences[j]
            sent_len = len(sent.split())
            if window_len + sent_len > chunk_size and window:
                break
            window.append(sent)
            window_len += sent_len
            j += 1
        if window:
            chunks.append(' '.join(window))
        # Move window forward by (chunk_size - overlap) words
        if window_len == 0:
            i += 1
        else:
            step = max(1, window_len - overlap)
            # Find the index to start next window
            words_seen = 0
            for k in range(i, len(sentences)):
                words_seen += len(sentences[k].split())
                if words_seen >= step:
                    i = k + 1
                    break
            else:
                break
    return chunks
# Prompt chaining for multi-step reasoning with Gemini
def prompt_chain(top_chunks, prompts, api_key):
    # If no relevant chunks or all are unknown, return a 'no results' message
    if not top_chunks or all(
        not c['chunk'].strip() or (
            c['meta'].get('title', '').strip() in ('', '[Unknown Title]') and
            c['meta'].get('author', '').strip() in ('', '[Unknown Author]') and
            c['meta'].get('publication_year', '').strip() in ('', '[Unknown Year]')
        ) for c in top_chunks):
        return 'No results found for your query.'
    context = ""
    answer = ""
    for idx, prompt_text in enumerate(prompts):
        # For first prompt, build context from top_chunks
        if idx == 0:
            # Build metadata summary with numbering, only unique PDFs in order
            doc_infos = []
            seen_pdfs = []
            pdf_to_number = {}
            for i, c in enumerate(top_chunks):
                meta = c['meta']
                pdf_id = meta.get('pdf', meta.get('file', '[Unknown]'))
                if pdf_id not in seen_pdfs:
                    seen_pdfs.append(pdf_id)
                    pdf_to_number[pdf_id] = len(seen_pdfs)
                    doc_infos.append(f"[{len(seen_pdfs)}] Title: {meta.get('title','') or '[Unknown]'}\n    Author: {meta.get('author','') or '[Unknown]'}\n    Year: {meta.get('publication_year','') or '[Unknown]'}\n    File: {pdf_id}")
                if len(doc_infos) >= 10:
                    break
            doc_info_str = "Top 10 relevant documents found (numbered for reference):\n" + "\n".join(doc_infos) + "\n\n"
            # Only include chunks from the top unique PDFs, in order
            chunk_context = "\n\n".join([
                f"[{pdf_to_number[c['meta'].get('pdf', c['meta'].get('file', '[Unknown]'))]}] From {c['meta'].get('pdf', c['meta'].get('file', '[Unknown]'))} (chunk {c['meta']['chunk_idx']}): {c['chunk']}"
                for c in top_chunks if c['meta'].get('pdf', c['meta'].get('file', '[Unknown]')) in pdf_to_number
            ])
            context = f"{doc_info_str}Context: {chunk_context}\n\nWhen answering, please reference the relevant thesis by its number in square brackets, e.g., [1], [2], etc., to indicate the source of each point.\n\n"
            context += (
                "Synthesize the findings from the top 5 relevant theses in response to the following question. "
                "Group your answer by key themes or outcomes relevant to the question. "
                "Write in plain text, paragraph style, without bullet points, asterisks, or markdown formatting. "
                "At the end of each paragraph, place in square brackets the number(s) of the most relevant thesis or theses (from the list above) that support the information in that paragraph, e.g., [1] or [2][3]. "
                "Do not place references anywhere else. Do not default to [1] for every paragraph—use the correct number(s) for each paragraph based on the supporting evidence. "
                "You must reference all top 5 unique theses at least once in your answer, distributing them across the overview. If a thesis is not referenced, add it to a relevant paragraph. "
                "Conclude with a summary paragraph that synthesizes the findings. After the summary, concatenate all referenced thesis numbers in square brackets (e.g., [1][2][3][4][5]), with no explanatory sentence or line break. "
                "Highlight relationships, causal links, and actionable insights. "
            )
        # Build prompt for Gemini
        full_prompt = f"{context}Question: {prompt_text}\nAnswer: "
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": api_key
        }
        data = {
            "contents": [
                {
                    "parts": [
                        {"text": full_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1600
            }
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        raw_answer = result['candidates'][0]['content']['parts'][0]['text'].strip()
        import re
        # --- Rearrangement logic ---
        ref_pattern = re.compile(r'\[(\d+)\]')
        # Find order of first appearance of each reference in Gemini output
        paragraphs = re.split(r'\n\s*\n', raw_answer)
        ref_order = []
        for para in paragraphs:
            for ref in ref_pattern.findall(para):
                if ref not in ref_order:
                    ref_order.append(ref)
        # Map old number to new number based on first appearance
        # Only consider numbers that are in allowed range
        allowed_numbers = [str(n) for n in range(1, len(seen_pdfs)+1)]
        ref_order = [r for r in ref_order if r in allowed_numbers]
        # If fewer than 5, fill in with missing numbers in original order
        for n in allowed_numbers:
            if n not in ref_order:
                ref_order.append(n)
        # Build mapping: old_num -> new_num
        old_to_new = {old: str(i+1) for i, old in enumerate(ref_order)}
        # Rearrange seen_pdfs and doc_infos to match new order
        seen_pdfs_new = [seen_pdfs[int(old)-1] for old in ref_order]
        doc_infos_new = []
        for i, pdf_id in enumerate(seen_pdfs_new):
            meta = None
            for c in top_chunks:
                meta_c = c['meta']
                pdf_id_c = meta_c.get('pdf', meta_c.get('file', '[Unknown]'))
                if pdf_id_c == pdf_id:
                    meta = meta_c
                    break
            doc_infos_new.append(f"[{i+1}] Title: {meta.get('title','') or '[Unknown]'}\n    Author: {meta.get('author','') or '[Unknown]'}\n    Year: {meta.get('publication_year','') or '[Unknown]'}\n    File: {pdf_id}")
        doc_info_str_new = "Top 10 relevant documents found (numbered for reference):\n" + "\n".join(doc_infos_new) + "\n\n"
        # Update chunk_context as well
        pdf_to_number_new = {pdf_id: i+1 for i, pdf_id in enumerate(seen_pdfs_new)}
        chunk_context_new = "\n\n".join([
            f"[{pdf_to_number_new[c['meta'].get('pdf', c['meta'].get('file', '[Unknown]'))]}] From {c['meta'].get('pdf', c['meta'].get('file', '[Unknown]'))} (chunk {c['meta']['chunk_idx']}): {c['chunk']}"
            for c in top_chunks if c['meta'].get('pdf', c['meta'].get('file', '[Unknown]')) in pdf_to_number_new
        ])
        # Replace all references in raw_answer according to old_to_new
        def replace_refs(text):
            return ref_pattern.sub(lambda m: f"[{old_to_new.get(m.group(1), m.group(1))}]", text)
        raw_answer_new = replace_refs(raw_answer)
        # Post-process: move all references to end of each paragraph (as before)
        def process_paragraphs(text):
            allowed_numbers_new = set(str(n) for n in range(1, len(seen_pdfs_new)+1))
            paragraphs = re.split(r'\n\s*\n', text)
            ref_pattern2 = re.compile(r'\[(\d+)\]')
            processed = []
            assigned_refs = []
            # Remove trailing reference-only paragraph if present
            if paragraphs and ref_pattern2.findall(paragraphs[-1]) and not re.search(r'[a-zA-Z]', paragraphs[-1]):
                paragraphs = paragraphs[:-1]

            n_body = max(1, len(paragraphs)-1)  # Exclude summary
            for i, para in enumerate(paragraphs):
                refs = [r for r in ref_pattern2.findall(para) if r in allowed_numbers_new]
                # Only keep up to 2 unique references per paragraph
                unique_refs = []
                for r in refs:
                    if r not in unique_refs:
                        unique_refs.append(r)
                    if len(unique_refs) == 2:
                        break
                para_clean = ref_pattern2.sub('', para).strip()
                para_clean = re.sub(r'\s+\.$', '.', para_clean)
                if i < n_body and unique_refs:
                    for r in unique_refs:
                        para_clean += f'[{r}]'
                        assigned_refs.append(r)
                processed.append(para_clean)
            # For the last paragraph (summary), append only unique refs actually assigned to body paragraphs
            if processed:
                summary_refs = []
                for r in assigned_refs:
                    if r not in summary_refs:
                        summary_refs.append(r)
                processed[-1] = re.sub(r'\s+\.$', '.', processed[-1])
                end_refs = re.findall(r'(\[\d+\])', processed[-1].split('.')[-1])
                end_refs_set = set([ref.strip('[]') for ref in end_refs])
                for r in summary_refs:
                    if r not in end_refs_set:
                        processed[-1] += f'[{r}]'
            return '\n\n'.join(processed)
        answer = process_paragraphs(raw_answer_new)
        # Update context for next step (with new doc_info_str and chunk_context)
        context = f"{doc_info_str_new}Context: {chunk_context_new}\n\nWhen answering, please reference the relevant thesis by its number in square brackets, e.g., [1], [2], etc., to indicate the source of each point.\n\n{answer}\n\n"
    return answer


import os
import glob
import re
import requests
import json
import numpy as np
from PyPDF2 import PdfReader
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi


# ChromaDB setup
import chromadb
import os
chromadb_persist_dir = os.path.abspath("RAG/chromadb_data")
print(f"[DEBUG] ChromaDB persistent directory (absolute): {chromadb_persist_dir}")
# Use PersistentClient API for ChromaDB >=1.1.0
chroma_client = chromadb.PersistentClient(path="RAG/chromadb_data")
COLLECTION_NAME = "thesis_chunks"
collection = chroma_client.get_or_create_collection(COLLECTION_NAME)


# 1. Extract and chunk text from all PDFs in a folder
def extract_and_chunk_pdfs(pdf_folder, chunk_size=500):
    # Load or create persistent index of already-processed files
    indexed_path = os.path.join(pdf_folder, "indexed_files.json")
    if os.path.exists(indexed_path):
        with open(indexed_path, "r", encoding="utf-8") as f:
            indexed_files = json.load(f)
    else:
        indexed_files = {}

    pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
    txt_files = [os.path.splitext(p)[0] + ".txt" for p in pdf_files if os.path.exists(os.path.splitext(p)[0] + ".txt")]
    print(f"[DEBUG] ChromaDB persistent directory: {os.path.abspath('./chromadb_data')}")
    print(f"[DEBUG] indexed_files.json path: {os.path.abspath(os.path.join(pdf_folder, 'indexed_files.json'))}")
    print(f"[DEBUG] ChromaDB collection count before indexing: {collection.count()}")
    # Only index files that are new or updated
    to_index = []
    for pdf_path, txt_path in zip(pdf_files, txt_files):
        mtime = os.path.getmtime(txt_path)
        if txt_path not in indexed_files or indexed_files[txt_path] != mtime:
            to_index.append((pdf_path, txt_path, mtime))

    if not to_index:
        print("[DEBUG] No new or changed PDFs to index. Skipping embedding and appending.")
    import pytesseract
    from pdf2image import convert_from_path
    import importlib.util
    from extract_metadata import extract_thesis_metadata

    pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
    # Show which PDFs are new (no .txt yet)
    new_pdfs = [p for p in pdf_files if not os.path.exists(os.path.splitext(p)[0] + ".txt")]
    print(f"[DEBUG] PDFs needing text extraction: {len(new_pdfs)}")
    for p in new_pdfs:
        print(f"    {os.path.basename(p)}")

    # Load or create persistent index of already-processed files
    indexed_path = os.path.join(pdf_folder, "indexed_files.json")
    if os.path.exists(indexed_path):
        with open(indexed_path, "r", encoding="utf-8") as f:
            indexed_files = json.load(f)
    else:
        indexed_files = {}

    # Extract text from new PDFs and save as .txt
    for pdf_path in new_pdfs:
        txt_path = os.path.splitext(pdf_path)[0] + ".txt"
        try:
            reader = PdfReader(pdf_path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            # If text is too short, fallback to OCR
            if len(text.strip()) < 100:
                print(f"[DEBUG] Fallback to OCR for {os.path.basename(pdf_path)}")
                images = convert_from_path(pdf_path)
                text = "\n".join(pytesseract.image_to_string(img) for img in images)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[DEBUG] Extracted text for {os.path.basename(pdf_path)}")
        except Exception as e:
            print(f"[ERROR] Failed to extract {os.path.basename(pdf_path)}: {e}")
            continue

    # Find all .txt files corresponding to PDFs
    txt_files = [os.path.splitext(p)[0] + ".txt" for p in pdf_files if os.path.exists(os.path.splitext(p)[0] + ".txt")]

    # Only index files that are new or updated
    to_index = []
    for pdf_path, txt_path in zip(pdf_files, txt_files):
        mtime = os.path.getmtime(txt_path)
        if pdf_path not in indexed_files or indexed_files[pdf_path] != mtime:
            to_index.append((pdf_path, txt_path, mtime))

    print(f"[DEBUG] PDFs to be indexed: {len(to_index)}")
    for pdf_path, txt_path, _ in to_index:
        print(f"    {os.path.basename(pdf_path)}")

    # Only embed and index new/changed files, append to ChromaDB
    embedder = SentenceTransformer('all-MiniLM-L6-v2')
    appended_chunks = []
    appended_metadata = []
    for pdf_path, txt_path, mtime in to_index:
        print(f"[DEBUG] Indexing: {os.path.basename(pdf_path)}")
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()
        meta = extract_thesis_metadata(text)
        meta["file"] = os.path.basename(txt_path)  # Use .txt as the source
        meta["chunk_idx"] = 0  # Will be set per chunk
        # Ensure 'university' is present
        if "university" not in meta:
            meta["university"] = ""
        chunks = sentence_chunking(text, chunk_size=chunk_size)
        chunk_embeddings = embed_chunks(chunks, embedder)
        chunk_metadatas = []
        for idx, chunk in enumerate(chunks):
            meta_copy = dict(meta)
            meta_copy["chunk_idx"] = idx
            # Ensure 'subjects' is always a string (ChromaDB does not allow lists)
            if "subjects" in meta_copy and isinstance(meta_copy["subjects"], list):
                meta_copy["subjects"] = ", ".join(str(s) for s in meta_copy["subjects"])
            # Replace None values with empty string for all metadata fields
            for k, v in meta_copy.items():
                if v is None:
                    meta_copy[k] = ""
            # Ensure 'university' is present in each chunk
            if "university" not in meta_copy:
                meta_copy["university"] = ""
            chunk_metadatas.append(meta_copy)
        # Append to ChromaDB (do not clear existing)
        ids = [f"{os.path.basename(txt_path)}_chunk_{i}" for i in range(len(chunks))]
        collection.add(
            embeddings=[list(map(float, emb)) for emb in chunk_embeddings],
            documents=chunks,
            metadatas=chunk_metadatas,
            ids=ids
        )
        appended_chunks.extend(chunks)
        appended_metadata.extend(chunk_metadatas)
        indexed_files[txt_path] = mtime

    # Save updated index
    with open(indexed_path, "w", encoding="utf-8") as f:
        json.dump(indexed_files, f, indent=2)

    print(f"[DEBUG] ChromaDB collection count after indexing: {collection.count()}")
    return appended_chunks, appended_metadata
    import pytesseract
    from pdf2image import convert_from_path
    import importlib.util
    pdf_files = glob.glob(os.path.join(pdf_folder, '*.pdf'))
    print(f"[DEBUG] Scanning for PDFs in: {pdf_folder}")
    print(f"[DEBUG] Found {len(pdf_files)} PDF(s):")
    for p in pdf_files:
        print(f"    {os.path.basename(p)}")
    # Show which PDFs are new (no .txt yet)
    new_pdfs = [p for p in pdf_files if not os.path.exists(os.path.splitext(p)[0] + ".txt")]
    print(f"[DEBUG] PDFs needing text extraction: {len(new_pdfs)}")
    for p in new_pdfs:
        print(f"    {os.path.basename(p)}")
    # Show which .txt files will be indexed (not in indexed_files or updated)
    # (Move this block after indexed_files is loaded)


# --- Minimal HTTP Server for Multi-Thesis RAG ---
import socketserver
from http.server import BaseHTTPRequestHandler

class MultiThesisRAGHTTPRequestHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        if self.path == "/health":
            # Return health and index info
            total_chunks = collection.count()
            # Try to count unique documents
            try:
                all_meta = collection.get()["metadatas"]
                unique_pdfs = set(m["pdf"] for m in all_meta if "pdf" in m)
            except Exception:
                unique_pdfs = set()
            # Count .txt files in RAG/theses (excluding non-thesis files)
            import glob
            import os
            thesis_dir = os.path.join("RAG", "theses")
            txt_files = [f for f in glob.glob(os.path.join(thesis_dir, '*.txt')) if os.path.isfile(f)]
            resp = {
                "status": "healthy",
                "total_documents": len(unique_pdfs),
                "total_chunks": total_chunks,
                "total_txt_files": len(txt_files)
            }
            self._set_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))

    def do_POST(self):
        if self.path == "/search":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                req = json.loads(post_data)
                question = req.get("question", "")
                if not question.strip():
                    raise ValueError("Missing question")
                embedder = SentenceTransformer('all-MiniLM-L6-v2')
                results = collection.query(
                    query_embeddings=[embedder.encode([question], convert_to_numpy=True)[0].tolist()],
                    n_results=50,  # Get more chunks to ensure enough unique PDFs
                    include=["documents", "metadatas", "distances"]
                )
                # Prepare top chunks for Gemini and filter by distance threshold
                top_chunks = []
                seen_files = set()
                documents = []
                DISTANCE_THRESHOLD = 1.5  # Lower means stricter relevance
                for i in range(len(results["documents"][0])):
                    meta = results["metadatas"][0][i]
                    file_name = meta.get("file", meta.get("pdf", ""))
                    score = float(results["distances"][0][i])
                    top_chunks.append({
                        "chunk": results["documents"][0][i],
                        "meta": meta,
                        "score": score
                    })
                    if score < DISTANCE_THRESHOLD and file_name and file_name not in seen_files:
                        doc = {
                            "title": meta.get("title", "[Unknown Title]"),
                            "author": meta.get("author", "[Unknown Author]"),
                            "publication_year": meta.get("publication_year", "[Unknown Year]"),
                            "abstract": meta.get("abstract", ""),
                            "file": file_name,
                            "degree": meta.get("degree", "Thesis"),
                            "call_no": meta.get("call_no", ""),
                            "subjects": meta.get("subjects", ""),
                            "university": meta.get("university", "")
                        }
                        documents.append(doc)
                        seen_files.add(file_name)
                    if len(documents) >= 10:
                        break


                # Call Gemini overview as long as there is at least 1 relevant chunk
                relevant_chunks = [c for c in top_chunks if c["score"] < DISTANCE_THRESHOLD]
                import os
                overview_msg = "No overview available."
                if relevant_chunks:
                    # Build context from up to 5 unique theses (by file/pdf)
                    unique_files = []
                    chunks_for_overview = []
                    for c in relevant_chunks:
                        file_name = c["meta"].get("file", c["meta"].get("pdf", ""))
                        if file_name and file_name not in unique_files:
                            unique_files.append(file_name)
                        if file_name in unique_files[:5]:
                            chunks_for_overview.append(c)
                        # Stop collecting if we have 5 unique sources
                        if len(unique_files) >= 5:
                            break
                    # Only keep chunks from the first 5 unique sources
                    chunks_for_overview = [c for c in chunks_for_overview if c["meta"].get("file", c["meta"].get("pdf", "")) in unique_files[:5]]
                    api_key = os.environ.get("GEMINI_API_KEY", "")
                    if api_key:
                        try:
                            prompts = [question]
                            overview_msg = prompt_chain(chunks_for_overview, prompts, api_key)
                        except Exception as e:
                            overview_msg = f"[Gemini error: {e}]"
                    else:
                        overview_msg = "No Gemini API key configured."
                else:
                    overview_msg = "No relevant information found for your query."

                # If no relevant chunks, also ensure no sources and clean up overview
                if not relevant_chunks:
                    documents = []
                    import re
                    overview_msg = re.sub(r"\\[\\d+\\]", "", overview_msg)

                resp = {
                    "overview": overview_msg,
                    "documents": documents,
                    "related_questions": []  # Placeholder
                }
                self._set_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))
            except Exception as e:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))

if __name__ == "__main__":
    pdf_folder = os.path.join("RAG", "theses")
    print("Extracting and chunking PDFs (only new/changed)...")
    appended_chunks, appended_metadata = extract_and_chunk_pdfs(pdf_folder)
    print(f"Appended {len(appended_chunks)} new/changed chunks.")
    # If ChromaDB is still empty but indexed_files.json exists, recover from index
    if collection.count() == 0:
        print("[RECOVERY] ChromaDB is empty. Attempting to recover from indexed_files.json...")
        recover_chromadb_from_index(pdf_folder)
        print(f"[RECOVERY] ChromaDB collection count after recovery: {collection.count()}")
    # Start HTTP server
    port = 5000
    print(f"Starting Multi-Thesis RAG HTTP server on port {port}...")
    with socketserver.TCPServer(("", port), MultiThesisRAGHTTPRequestHandler) as httpd:
        print(f"Server started at http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
            httpd.shutdown()