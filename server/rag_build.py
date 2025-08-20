"""
Script to build a vector index from multiple knowledge bases.

This utility reads two JSON files – ``kb.json`` and ``mb.json`` – and
converts them into a collection of documents suitable for insertion
into a Chroma vector database. It then computes embeddings for each
document using OpenAI's embedding API and writes them into the
persistent store configured via the ``RAG_PERSIST_DIR`` environment
variable or falling back to a ``rag_store`` directory in the same
folder.

Run this script before launching the server to populate the search
index. If you subsequently modify the knowledge files, run this
builder again to refresh the index. The script clears any existing
collection named ``health_kb`` before inserting new data.
"""

import json
import os
from typing import Iterable, Tuple, List, Dict

from dotenv import load_dotenv
import openai
from chromadb import Client
from chromadb.config import Settings


load_dotenv()

# Paths to knowledge files. These are relative to this script's
# directory. If you wish to change the location of the knowledge
# sources, modify these constants or pass them via environment
# variables.
BASE_DIR = os.path.dirname(__file__)
KB_FILE = os.environ.get("KB_FILE", os.path.join(BASE_DIR, "kb.json"))
MB_FILE = os.environ.get("MB_FILE", os.path.join(BASE_DIR, "mb.json"))

# Ollama configuration for embeddings. The embedding model should match
# the one used in app.py for consistency.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# We'll use requests to call Ollama API directly for embeddings
import requests

# Persistent directory for Chroma
PERSIST_DIR = os.environ.get(
    "RAG_PERSIST_DIR", os.path.join(BASE_DIR, "rag_store")
)


def load_kb() -> List[Dict]:
    """Load the structured knowledge base from kb.json.

    Returns a list of topic dictionaries. If the file does not exist
    or is malformed, an empty list is returned and an error is logged.
    """
    if not os.path.exists(KB_FILE):
        print(f"Warning: {KB_FILE} does not exist. No structured knowledge will be loaded.")
        return []
    try:
        with open(KB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("knowledge_base", [])
    except Exception as exc:
        print(f"Error reading {KB_FILE}: {exc}")
        return []


def flatten_kb(topics: Iterable[Dict]) -> Iterable[Tuple[str, Dict]]:
    """Flatten the structured kb into (document, metadata) pairs.

    Each topic in kb.json may contain nested sections with lists,
    dictionaries or strings. This function walks through that
    structure and yields concatenated text blocks. The metadata
    contains the topic_id, topic_name, sources and the section name.
    """
    for topic in topics:
        topic_id = topic.get("topic_id")
        topic_name = topic.get("topic_name")
        sources = topic.get("sources", [])
        data = topic.get("data", {})
        # If data is missing or not a dict, skip this topic
        if not isinstance(data, dict):
            continue
        for section, payload in data.items():
            # Collect parts of text from the payload. We handle
            # dictionaries, lists and primitive types.
            text_parts: List[str] = []
            if isinstance(payload, dict):
                for k, v in payload.items():
                    if isinstance(v, list):
                        for item in v:
                            # Convert dict/list items into readable strings
                            text_parts.append(f"{k}: {item}")
                    else:
                        text_parts.append(f"{k}: {v}")
            elif isinstance(payload, list):
                for item in payload:
                    text_parts.append(str(item))
            else:
                text_parts.append(str(payload))
            # Compose final document text with a header so it's clear
            # which topic and section this content belongs to.
            header = f"[{topic_name} / {section}]"
            content = header + "\n" + "\n".join(text_parts)
            # Convert sources list to string for ChromaDB compatibility
            sources_str = sources
            if isinstance(sources, list):
                sources_str = ", ".join(sources)
            elif not isinstance(sources, str):
                sources_str = str(sources)
            
            metadata = {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "section": section,
                "sources": sources_str,
            }
            yield content, metadata


def load_mb() -> List[Dict]:
    """Load the mini chunks from mb.json.

    The mb.json file is expected to be a JSON array of objects with at
    least the keys ``chunk_text`` and ``metadata``. If the file
    doesn't exist or is malformed, an empty list is returned.
    """
    if not os.path.exists(MB_FILE):
        print(f"Warning: {MB_FILE} does not exist. No freeform knowledge will be loaded.")
        return []
    try:
        with open(MB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"Warning: {MB_FILE} is not a JSON list. Skipping.")
            return []
        return data
    except Exception as exc:
        print(f"Error reading {MB_FILE}: {exc}")
        return []


def flatten_mb(chunks: Iterable[Dict]) -> Iterable[Tuple[str, Dict]]:
    """Flatten the list of mb chunks into (document, metadata) pairs."""
    for item in chunks:
        text = item.get("chunk_text")
        meta = item.get("metadata", {})
        if not text or not isinstance(text, str):
            continue
        # Convert sources list to string for ChromaDB compatibility
        sources = meta.get("sources")
        if sources:
            if isinstance(sources, list):
                meta["sources"] = ", ".join(sources)
            elif not isinstance(sources, str):
                meta["sources"] = str(sources)
        yield text, meta


def build_index():
    """Build the Chroma collection from kb.json and mb.json."""
    client = Client(Settings(is_persistent=True, persist_directory=PERSIST_DIR))
    collection = client.get_or_create_collection("health_kb")
    # Clear existing documents to avoid duplicates. This will wipe the
    # collection; if you need incremental updates you can remove this
    # call and rely on unique ids instead.
    try:
        collection.delete(where={})
    except Exception:
        # Delete may fail if the collection is empty, ignore
        pass
    # Prepare documents and metadata lists
    docs: List[str] = []
    metas: List[Dict] = []
    # Flatten KB
    topics = load_kb()
    for content, meta in flatten_kb(topics):
        docs.append(content)
        metas.append(meta)
    # Flatten MB
    chunks = load_mb()
    for content, meta in flatten_mb(chunks):
        docs.append(content)
        metas.append(meta)
    if not docs:
        print("No documents found; nothing to index.")
        return
    # Generate embeddings in batches to respect token limits.
    embeddings: List[List[float]] = []
    batch_size = 64
    for i in range(0, len(docs), batch_size):
        batch_docs = docs[i : i + batch_size]
        try:
            # Generate embeddings using Ollama API
            for doc in batch_docs:
                ollama_response = requests.post(
                    f"{OLLAMA_BASE_URL}/api/embeddings",
                    json={"model": OLLAMA_EMBED_MODEL, "prompt": doc}
                )
                if ollama_response.status_code != 200:
                    raise RuntimeError(f"Error from Ollama: {ollama_response.text}")
                embeddings.append(ollama_response.json()["embedding"])
        except Exception as exc:
            raise RuntimeError(f"Error generating embeddings: {exc}")
    # Create unique ids for each document
    ids = [f"doc-{i}" for i in range(len(docs))]
    # Add to collection
    collection.add(documents=docs, metadatas=metas, ids=ids, embeddings=embeddings)
    print(f"Indexed {len(docs)} documents into collection 'health_kb' at '{PERSIST_DIR}'.")


if __name__ == "__main__":
    build_index()