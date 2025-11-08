# Controlled vocabulary for main subjects
MAIN_SUBJECTS = [
    "Agriculture",
    "Anthropology",
    "Archaeology",
    "Architecture",
    "Astronomy",
    "Biology",
    "Botany",
    "Chemistry",
    "Communications",
    "Computer Science",
    "Ecology",
    "Education",
    "Engineering",
    "Information and Communications Technology",
    "Environmental Science",
    "Fisheries",
    "Food Science and Technology",
    "Forestry",
    "Genetics",
    "Geology",
    "Health and Wellness",
    "Hydrology",
    "Industry",
    "Library and Information Science",
    "Livelihood",
    "Marine Science",
    "Mathematics",
    "Medicine",
    "Meteorology",
    "Nutrition",
    "Physics",
    "Science and Technology",
    "Statistics",
    "Social Sciences",
    "Veterinary Medicine",
    "Zoology",
    "General Works"
]

# Rule-based mapping from degree/title terms to main subject
DEGREE_TO_MAIN_SUBJECT = {
    'agronomy': 'Agriculture',
    'horticulture': 'Agriculture',
    'plant breeding': 'Agriculture',
    'soil science': 'Agriculture',
    'entomology': 'Agriculture',
    'botany': 'Botany',
    'forestry': 'Forestry',
    'environmental science': 'Environmental Science',
    'marine science': 'Marine Science',
    'applied nutrition': 'Food Science and Technology',
    'food science': 'Food Science and Technology',
    'genetics': 'Genetics',
    'mathematics': 'Mathematics',
    'statistics': 'Statistics',
    'physics': 'Physics',
    'chemistry': 'Chemistry',
    'engineering': 'Engineering',
    'computer science': 'Computer Science',
    'information technology': 'Computer Science',
    'social science': 'Social Sciences',
    'economics': 'Social Sciences',
    'education': 'Education',
    'general science': 'General Works',
}

def extract_thesis_metadata(text):
    import re
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity

    meta = {}
    lines = text.splitlines()

    # Title: first non-empty line
    for l in lines:
        if l.strip():
            meta["title"] = l.strip()
            break

    # Author: look for a line with all uppercase or title case, not matching section headers
    for l in lines[1:10]:
        if l.strip() and not re.match(r'^(chapter|introduction|background|review|statement|objectives|scope|significance|summary|conclusion|references|acknowledgments?)', l, re.I):
            meta["author"] = l.strip()
            break

    # Degree: look for 'Master', 'Doctor', etc.
    for l in lines:
        if re.search(r'(Master|Doctor|Bachelor|Philosophy|Science|Arts|Engineering)', l, re.I):
            meta["degree"] = l.strip()
            break

    # University: look for 'University'
    for l in lines:
        if 'university' in l.lower():
            meta["university"] = l.strip()
            break

    # Publication year: look for a line with a 4-digit year (e.g., 2018)
    for l in lines[1:20]:
        m = re.search(r'(19|20)\d{2}', l)
        if m:
            meta["publication_year"] = m.group(0)
            break

    # Abstract: text between 'ABSTRACT' and the next major section header, allow multi-line, avoid premature cutoff
    abstract = []
    in_abstract = False
    idx = 0
    while idx < len(lines):
        l = lines[idx]
        if not in_abstract and l.upper().startswith("ABSTRACT"):
            in_abstract = True
            idx += 1
            continue
        if in_abstract:
            # Stop at major section headers, roman/numbered section headers with or without section names
            if re.match(r'^(CHAPTER|INTRODUCTION|BACKGROUND|REVIEW|STATEMENT|OBJECTIVES|SCOPE|SIGNIFICANCE|SUMMARY|CONCLUSION|REFERENCES|ACKNOWLEDGMENTS?)', l, re.I):
                break
            # Match lines like 'I. INTRODUCTION', 'II. METHODS', '1. INTRODUCTION', etc.
            if re.match(r'^([IVXLCDM]+|\d+)\.\s*([A-Z][A-Z ]+)?$', l.strip()):
                break
            if l.strip().lower().startswith("keywords:") or l.strip().upper().startswith("PACS:"):
                break
            line = l.strip()
            abstract.append(line)
        idx += 1
    meta["abstract"] = " ".join(abstract).strip()

    # Subjects/keywords: look for a line starting with 'Keywords:' or 'PACS:' (multi-line)
    keywords = []
    for i, l in enumerate(lines):
        if l.lower().startswith("keywords:") or l.strip().upper().startswith("PACS:"):
            # Remove the 'Keywords:' or 'PACS:' prefix and split by comma/semicolon
            key_line = l.split(':', 1)[-1] if ':' in l else l
            key_line = key_line.replace('Keywords', '').replace('PACS', '').replace(':', '').strip()
            if key_line:
                keywords += [k.strip() for k in re.split(r'[;,]', key_line) if k.strip()]
            # Also check following lines until a section header or blank line
            for j in range(i+1, len(lines)):
                next_l = lines[j].strip()
                if not next_l or re.match(r'^(CHAPTER|INTRODUCTION|BACKGROUND|REVIEW|STATEMENT|OBJECTIVES|SCOPE|SIGNIFICANCE|SUMMARY|CONCLUSION|REFERENCES|ACKNOWLEDGMENTS?)', next_l, re.I) or re.match(r'^[IVXLCDM]+\.[ \t]', next_l, re.I) or re.match(r'^\d+\.[ \t]', next_l):
                    break
                keywords += [k.strip() for k in re.split(r'[;,]', next_l) if k.strip()]
            break

    # Guarantee at least one subject, and main subject is first
    def get_main_subject(subjects, title, degree, abstract):
        # 1. Rule-based mapping from degree/title
        for k, v in DEGREE_TO_MAIN_SUBJECT.items():
            if k in (degree or '').lower() or k in (title or '').lower():
                return v
        # 2. If any subject matches a main subject, use it
        for s in subjects:
            for main in MAIN_SUBJECTS:
                if s.lower() == main.lower():
                    return main
        # 3. Fallback: use embedding similarity if available
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.metrics.pairwise import cosine_similarity
            model = SentenceTransformer('all-MiniLM-L6-v2')
            main_embs = model.encode(MAIN_SUBJECTS)
            context = ((degree or "") + ". " + (title or "")).strip()
            if context:
                context_emb = model.encode([context])[0]
                sims = cosine_similarity([context_emb], main_embs)[0]
                best_idx = int(sims.argmax())
                return MAIN_SUBJECTS[best_idx]
            if abstract:
                context_emb = model.encode([abstract])[0]
                sims = cosine_similarity([context_emb], main_embs)[0]
                best_idx = int(sims.argmax())
                return MAIN_SUBJECTS[best_idx]
        except Exception:
            pass
        # 4. Fallback: use 'General Works' if present, else first main subject
        for main in MAIN_SUBJECTS:
            if main == "General Works":
                return main
        return MAIN_SUBJECTS[0]

    subjects = [s for s in keywords if s]
    title = meta.get("title", "")
    degree = meta.get("degree", "")
    abstract = meta.get("abstract", "")
    main_subject = get_main_subject(subjects, title, degree, abstract)
    # Remove any duplicate of main subject in subjects
    subjects = [s for s in subjects if main_subject.lower() != s.lower()]
    meta["main_subject"] = main_subject
    meta["subjects"] = [main_subject] + subjects if subjects else [main_subject]

    return meta