"""
rag_ingestion.py — Agent 1 RAG Pipeline (v3)

Changes from v2:
- _find_source_dir() now selects the directory that contains the most
  expected manifest filenames, not just the first with any .txt files.
- retrieve_with_metadata() is a new public function that returns
  (chunks_text, retrieved_labs) for direct use in run_agent1(),
  enabling retrieval enforcement in code rather than just prompt text.

Usage:
    python rag_ingestion.py              # build index
    python rag_ingestion.py --rebuild    # force rebuild
    python rag_ingestion.py --verify     # verify existing index
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import AzureOpenAIEmbeddings

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
CANDIDATE_DIRS = [
    REPO_ROOT / "data" / "reference",
    REPO_ROOT,
]
INDEX_DIR = REPO_ROOT / "faiss_index"

# ── Canonical lab manifest ─────────────────────────────────────────────────────
LAB_FILENAME_MAP: dict[str, str] = {
    "agriculture_and_climate_change_learning_lab.txt":     "Agriculture & Climate Change",
    "climate_impacts_and_solutions_with_en_roads.txt":     "En-ROADS Climate Modeling",
    "invasive_species_learning_lab.txt":                   "Invasive Species",
    "sea_level_rise_learning_lab.txt":                     "Sea Level Rise",
    "climate_change_and_health_learning_lab.txt":          "Climate Change & Health",
    "civics_climate_action_learning_lab.txt":              "Civics & Climate Action",
    "climate_justice_and_equity_learning_lab.txt":         "Climate Justice & Equity",
    "climate_migration_learning_lab.txt":                  "Climate Migration",
    "floods_and_droughts_learning_lab.txt":                "Floods & Droughts",
    "wildfires_learning_lab_teacher_guide.txt":            "Wildfires",
    "renewable_energy_learning_lab.txt":                   "Renewable Energy",
}

EXPECTED_COUNT = 11
TRACK_A_LABS = {"En-ROADS Climate Modeling"}


# ── File discovery & validation ────────────────────────────────────────────────

def _find_source_dir() -> Path:
    """
    Return the candidate directory that contains the most expected manifest
    filenames. Raises FileNotFoundError if no candidate contains any.
    This prevents picking a directory that has unrelated .txt files.
    """
    best_dir: Path | None = None
    best_count = 0
    expected_fnames = set(LAB_FILENAME_MAP.keys())

    for d in CANDIDATE_DIRS:
        if not d.exists():
            continue
        found = {f.name for f in d.glob("*.txt")} & expected_fnames
        if len(found) > best_count:
            best_count = len(found)
            best_dir = d

    if best_dir is None or best_count == 0:
        raise FileNotFoundError(
            f"No expected lab .txt files found in any candidate directory: {CANDIDATE_DIRS}\n"
            "Place all 11 learning lab .txt files in data/reference/"
        )
    return best_dir


def validate_lab_files() -> dict[str, Path]:
    """
    Validate exactly the 11 expected lab files are present.
    Returns: {canonical_lab_name: file_path}
    Raises FileNotFoundError if any expected file is missing.
    Prints warning for unexpected extra .txt files (does not index them).
    """
    source_dir = _find_source_dir()
    all_txt = {f.name: f for f in source_dir.glob("*.txt")}

    missing = [fname for fname in LAB_FILENAME_MAP if fname not in all_txt]
    if missing:
        raise FileNotFoundError(
            f"Missing {len(missing)} expected lab file(s) in {source_dir}:\n"
            + "\n".join(f"  - {f}" for f in sorted(missing))
            + "\n\nAll 11 files must be present to build a complete index."
        )

    unexpected = [f for f in all_txt if f not in LAB_FILENAME_MAP]
    if unexpected:
        print(f"[rag_ingestion] WARNING: {len(unexpected)} unexpected .txt file(s) "
              f"in {source_dir} — NOT indexed:")
        for f in sorted(unexpected):
            print(f"  - {f}")

    return {
        LAB_FILENAME_MAP[fname]: path
        for fname, path in all_txt.items()
        if fname in LAB_FILENAME_MAP
    }


# ── Azure embeddings ───────────────────────────────────────────────────────────

def _make_embeddings() -> AzureOpenAIEmbeddings:
    required = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"Missing environment variables: {missing}\n"
            "Copy .env.example to .env and fill in your Azure credentials."
        )
    return AzureOpenAIEmbeddings(
        azure_deployment=os.getenv("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-large"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )


# ── Build / load ───────────────────────────────────────────────────────────────

def build_index(force: bool = False) -> FAISS:
    """Validate all 11 lab files, chunk, embed, save FAISS index."""
    if INDEX_DIR.exists() and not force:
        print(f"[rag_ingestion] Index exists at {INDEX_DIR}. Use --rebuild to recreate.")
        return load_index()

    lab_paths = validate_lab_files()
    embeddings = _make_embeddings()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_docs = []
    for lab_name, fpath in sorted(lab_paths.items()):
        track = "A" if lab_name in TRACK_A_LABS else "B"
        text = fpath.read_text(encoding="utf-8", errors="replace")
        chunks = splitter.create_documents(
            texts=[text],
            metadatas=[{"lab_name": lab_name, "track": track, "source_file": fpath.name}],
        )
        all_docs.extend(chunks)
        print(f"  ✓  {lab_name} ({len(chunks)} chunks, Track {track})")

    print(f"\n[rag_ingestion] Embedding {len(all_docs)} chunks across {EXPECTED_COUNT} labs...")
    import time
    batch_size = 100
    vectorstore = None
    total_batches = (len(all_docs) - 1) // batch_size + 1
    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"  Embedding batch {batch_num}/{total_batches} ({len(batch)} chunks)...")
        if vectorstore is None:
            vectorstore = FAISS.from_documents(batch, embeddings)
        else:
            vectorstore.add_documents(batch)
        if i + batch_size < len(all_docs):
            time.sleep(15)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(INDEX_DIR))
    print(f"[rag_ingestion] Index saved → {INDEX_DIR}/")
    return vectorstore


def load_index() -> FAISS:
    if not INDEX_DIR.exists():
        raise FileNotFoundError(
            f"No FAISS index at {INDEX_DIR}. Run: python rag_ingestion.py"
        )
    embeddings = _make_embeddings()
    return FAISS.load_local(
        str(INDEX_DIR), embeddings, allow_dangerous_deserialization=True
    )


def get_retriever(k: int = 5):
    """Return a LangChain retriever for use by Agent 1."""
    return load_index().as_retriever(
        search_type="similarity",
        search_kwargs={"k": k},
    )


def retrieve_with_metadata(query: str, k: int = 5) -> tuple[str, list[dict]]:
    """
    Execute retrieval and return both a formatted text block for prompt
    injection AND structured metadata for inspection.

    Returns:
        chunks_text: formatted string ready for injection into system prompt
        chunk_metadata: list of {lab_name, track, preview} dicts for QA/debug
    """
    retriever = get_retriever(k=k)
    docs = retriever.invoke(query)
    if not docs:
        return "No relevant lab content found for this query.", []

    parts = []
    metadata = []
    for doc in docs:
        lab   = doc.metadata.get("lab_name", "Unknown Lab")
        track = doc.metadata.get("track", "?")
        preview = doc.page_content[:120].replace("\n", " ").strip()
        parts.append(f"[SOURCE: {lab} | Track {track}]\n{doc.page_content.strip()}")
        metadata.append({"lab_name": lab, "track": track, "preview": preview})

    return "\n\n---\n\n".join(parts), metadata


# ── Verification ───────────────────────────────────────────────────────────────

def verify_index():
    print("\n[rag_ingestion] Verifying index...")
    test_queries = [
        ("teacher", "NGSS chemistry alignment renewable energy curriculum"),
        ("student", "civics climate action student project community"),
        ("math",    "En-ROADS carbon calculator electricity emissions factor"),
    ]
    all_ok = True
    for mode, query in test_queries:
        text, meta = retrieve_with_metadata(query, k=3)
        if not meta:
            print(f"  ✗ [{mode}] No results for: {query}")
            all_ok = False
        else:
            labs = [m["lab_name"] for m in meta]
            print(f"  ✓ [{mode}] {len(meta)} docs — labs: {labs}")
    if not all_ok:
        print("[rag_ingestion] Verification FAILED.\n")
        sys.exit(1)
    print("[rag_ingestion] Verification passed.\n")


if __name__ == "__main__":
    rebuild = "--rebuild" in sys.argv
    do_verify = "--verify" in sys.argv
    if do_verify and INDEX_DIR.exists() and not rebuild:
        verify_index()
    else:
        build_index(force=rebuild)
        if do_verify:
            verify_index()
