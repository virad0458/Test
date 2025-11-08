import os
import re
import shutil

# Folder containing your thesis .txt files
THESIS_DIR = os.path.join("RAG", "theses")
BACKUP_DIR = os.path.join(THESIS_DIR, "backup_before_cleaning")

# Patterns to remove: page numbers (lines that are just numbers), and common header/footer patterns
PAGE_NUMBER_PATTERN = re.compile(r"^\s*\d+\s*$")
HEADER_FOOTER_PATTERNS = [
    re.compile(r"^\s*Page \d+\s*$", re.IGNORECASE),
    # Add more patterns here if you have custom headers/footers
]

def is_noise_line(line):
    if PAGE_NUMBER_PATTERN.match(line):
        return True
    for pat in HEADER_FOOTER_PATTERNS:
        if pat.match(line):
            return True
    return False

def clean_file(filepath, backup_dir):
    filename = os.path.basename(filepath)
    backup_path = os.path.join(backup_dir, filename)
    shutil.copy2(filepath, backup_path)
    with open(backup_path, 'r', encoding='utf-8') as fin:
        lines = fin.readlines()
    cleaned_lines = [line for line in lines if not is_noise_line(line)]
    with open(filepath, 'w', encoding='utf-8') as fout:
        fout.writelines(cleaned_lines)
    print(f"Cleaned: {filename} (backup saved)")

def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for fname in os.listdir(THESIS_DIR):
        if fname.endswith('.txt'):
            fpath = os.path.join(THESIS_DIR, fname)
            clean_file(fpath, BACKUP_DIR)
    print("All files cleaned. Backups are in:", BACKUP_DIR)

if __name__ == "__main__":
    main()