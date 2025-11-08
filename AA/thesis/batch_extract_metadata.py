import os
import json
from extract_metadata import extract_thesis_metadata

def main():
    theses_dir = os.path.join("RAG", "theses")
    out_path = os.path.join(theses_dir, "all_metadata.json")
    txt_files = [f for f in os.listdir(theses_dir) if f.endswith(".txt")]
    all_metadata = {}
    for fname in txt_files:
        fpath = os.path.join(theses_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            print(f"Skipping {fname}: file is empty.")
            continue
        meta = extract_thesis_metadata(text)
        # Only skip if meta is not a dict or is completely empty
        if not meta or not isinstance(meta, dict):
            print(f"Skipping {fname}: could not extract any metadata.")
            continue
        meta["file"] = fname
        all_metadata[fname] = meta
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_metadata, f, indent=2, ensure_ascii=False)
    print(f"Extracted metadata for {len(all_metadata)} files. Output: {out_path}")

if __name__ == "__main__":
    main()