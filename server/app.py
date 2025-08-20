"""
FastAPI application for the Baymax Assistant.

This app exposes three primary endpoints:

* ``/api/chat`` – simple chat endpoint without additional knowledge retrieval.
* ``/api/ask_rag`` – chat endpoint that augments the request with
  contextual information pulled from a vector database built from
  multiple knowledge bases (``kb.json`` and ``mb.json``).
* ``/api/tts`` – text‑to‑speech endpoint powered by ElevenLabs that
  returns audio for the assistant's response. The voice can be
  selected via the ``mode`` field (``pro``, ``max`` or ``kids``).

The assistant is designed to speak like Baymax: calm, reassuring
and never diagnosing or prescribing. It replies in Indonesian and
includes brief suggestions where appropriate. When using RAG, the
sources for the answer are surfaced back to the client.

Before running this server you should build the vector store by
executing ``rag_build.py``. The path to the persistent store is
controlled via the ``RAG_PERSIST_DIR`` environment variable and
defaults to a ``rag_store`` directory alongside this file.
"""

import io
import os
from typing import List, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import openai
from chromadb import Client
from chromadb.config import Settings


# Load environment variables from a .env file if present. This call is
# idempotent – if no .env exists, nothing happens. It allows the
# application to pick up API keys and other secrets without hardcoding
# them into the code.
load_dotenv()

# Initialise the FastAPI app with production-ready configuration
# CORS is configured based on environment - restrictive for production
DEBUG_MODE = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

app = FastAPI(
    title="Baymax Assistant API",
    description="AI Health Assistant API",
    version="1.0.0",
    debug=DEBUG_MODE
)

# Configure CORS based on environment
if DEBUG_MODE:
    # Development: Allow all origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Production: Restrict origins
    allowed_origins = [f"https://{host}" for host in ALLOWED_HOSTS] + [f"http://{host}" for host in ALLOWED_HOSTS]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# Groq API key and model name are loaded from the environment.
# Using Groq API which is compatible with OpenAI format.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY environment variable is not set. Please provide your Groq key via .env or environment."
    )
GROQ_MODEL_NAME = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# TTS configuration
TTS_BASE_URL = os.environ.get("TTS_BASE_URL", "http://localhost:5050")
TTS_MODEL = os.environ.get("TTS_MODEL", "tts-1")

# ElevenLabs TTS configuration (fallback)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
VOICE_ID_PRO = os.environ.get("ELEVENLABS_VOICE_ID_PRO")
VOICE_ID_MAX = os.environ.get("ELEVENLABS_VOICE_ID_MAX")
VOICE_ID_KIDS = os.environ.get("ELEVENLABS_VOICE_ID_KIDS")

# Directory containing the persisted chroma database. If you change
# this path, ensure you run rag_build.py again so the new location
# contains an index built from the knowledge files.
BASE_DIR = os.path.dirname(__file__)
PERSIST_DIR = os.environ.get(
    "RAG_PERSIST_DIR", os.path.join(BASE_DIR, "rag_store")
)

# Initialise Groq client using OpenAI-compatible API format.
# Groq provides OpenAI-compatible endpoints.
# Production timeout settings
CLIENT_TIMEOUT = 60 if not DEBUG_MODE else 30
groq_client = openai.OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
    timeout=CLIENT_TIMEOUT
)

# Create or open the Chroma client. We don't rebuild the index in
# production; rag_build.py is responsible for populating this store.
chroma_client = Client(Settings(is_persistent=True, persist_directory=PERSIST_DIR))
kb_collection = chroma_client.get_or_create_collection("health_kb")

# Ollama configuration for embeddings
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Baymax system prompt used for both chat and RAG. This prompt gently
# reminds the model to avoid diagnosis or prescribing medication, to
# keep answers concise and helpful, and to respond in Indonesian.
BAYMAX_SYSTEM_PROMPT = (
    "Anda adalah Baymax, asisten kesehatan pribadi yang tenang dan empatik. "
    "Anda tidak mendiagnosis penyakit, tidak meresepkan obat, dan tidak memberikan rekomendasi medis yang bersifat spesifik. "
    "Tugas Anda adalah memberikan informasi umum, tips gaya hidup, dan pertolongan awal yang aman berdasarkan pertanyaan pengguna atau konteks yang diberikan. "
    "Jika pertanyaan berkaitan dengan gejala berat, Anda harus menyarankan untuk berkonsultasi langsung dengan tenaga medis atau layanan darurat. "
    "Tulislah jawaban dalam Bahasa Indonesia dengan 2–4 kalimat, kemudian berikan 2–3 bullet point saran jika relevan. "
    "Akhiri jawaban dengan pertanyaan singkat atau harapan baik."
)


# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------

def get_voice_id(mode: str) -> str:
    """Return the ElevenLabs voice ID based on the requested mode.

    Modes map to environment variables defined in .env. If an unknown
    mode is supplied, fall back to the Pro voice. If no voice ID is
    configured for the selected mode, raise an exception to avoid
    silent failures.
    """
    m = (mode or "pro").lower()
    if m == "max":
        vid = VOICE_ID_MAX
    elif m == "kids":
        vid = VOICE_ID_KIDS
    else:
        vid = VOICE_ID_PRO
    if not vid:
        raise HTTPException(status_code=500, detail=f"Voice ID for mode '{m}' is not configured.")
    return vid


def retrieve_context(query: str, k: int = 4) -> Tuple[List[str], List[dict]]:
    """Retrieve the most relevant documents from the vector store.

    Given a query, compute its embedding and ask Chroma to return the
    top-k matching documents along with their metadata. The number of
    results can be tuned via the ``k`` parameter.
    """
    # Compute the embedding for the incoming query using Ollama
    import requests
    ollama_response = requests.post(
        f"{OLLAMA_BASE_URL}/api/embeddings",
        json={"model": OLLAMA_EMBED_MODEL, "prompt": query}
    )
    if ollama_response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Error from Ollama: {ollama_response.text}")
    query_emb = ollama_response.json()["embedding"]
    # Query Chroma. We ask to return the documents and metadata; ids
    # are not needed here. If the index is empty, this will return
    # empty lists.
    results = kb_collection.query(
        query_embeddings=[query_emb],
        n_results=k,
        include=["documents", "metadatas"],
    )
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return docs, metas


def build_rag_prompt(user_question: str, context_docs: List[str], context_metas: List[dict]) -> Tuple[str, List[str]]:
    """Construct a prompt for the LLM using retrieved context.

    The prompt contains the system directive, the concatenated context
    documents (with a separator), and the user question. Metadata
    sources are collected and returned separately for inclusion in the
    response payload.
    """
    # Concatenate context passages separated by a delineator. We
    # include headers in the documents themselves when building the
    # index so we don't need to add them here.
    context_section = "\n\n---\n".join(context_docs)
    # Collect unique sources from metadata. The metadata stored in
    # kb_collection is a dictionary containing at least a 'sources'
    # field which may be a comma-separated string of agencies or
    # organisations.
    source_set = set()
    for meta in context_metas:
        sources = meta.get("sources")
        if not sources:
            continue
        # metadata can come as a list or a single string
        if isinstance(sources, list):
            source_set.update(sources)
        elif isinstance(sources, str):
            for part in sources.split(","):
                source_set.add(part.strip())
    sorted_sources = sorted(source_set)
    # Construct the complete prompt. The context is clearly separated
    # from the user question so the model knows where to look for
    # reference material. We instruct the model to cite the sources
    # collected above.
    prompt = (
        f"{BAYMAX_SYSTEM_PROMPT}\n\n"
        "[KONTEKS]\n"
        f"{context_section}\n\n"
        "[PERTANYAAN PENGGUNA]\n"
        f"{user_question}\n\n"
        "[PETUNJUK]\n"
        "Gunakan informasi dari [KONTEKS] untuk menjawab pertanyaan. Jika konteks tidak relevan, berikan jawaban umum sesuai kebijaksanaan Anda. "
        "Selalu cantumkan bagian 'Sumber:' di akhir jawaban yang berisi nama lembaga, dipisahkan oleh koma, dari sumber yang digunakan. "
        "Jika Anda tidak dapat menemukan jawaban yang relevan atau yakin, katakan bahwa Anda tidak tahu dan sarankan untuk berkonsultasi dengan tenaga medis."
    )
    return prompt, sorted_sources


# ----------------------------------------------------------------------------
# Data models for request bodies
# ----------------------------------------------------------------------------

class ChatBody(BaseModel):
    message: str


class RagBody(BaseModel):
    message: str


class TTSBody(BaseModel):
    text: str
    mode: str | None = "pro"


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------

@app.post("/api/chat")
async def chat_endpoint(body: ChatBody):
    """Handle a plain chat request without RAG context.

    The system prompt ensures the model behaves as Baymax and
    communicates in Indonesian. The user's message is appended to the
    messages list. The response from the model is returned as JSON.
    """
    question = (body.message or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    messages = [
        {"role": "system", "content": BAYMAX_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL_NAME,
            messages=messages,
            temperature=0.2,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Error from Groq: {ex}")
    answer = completion.choices[0].message.content
    return JSONResponse({"text": answer})


@app.post("/api/ask_rag")
async def rag_endpoint(body: RagBody):
    """Handle a chat request augmented with retrieved knowledge.

    The incoming question is used to query the vector store for relevant
    passages. These are fed into the LLM along with the Baymax
    directive. The LLM response and the list of sources are returned.
    """
    question = (body.message or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    # Retrieve context from the vector store. If the store has no data
    # (e.g. build script not run) the returned lists will be empty.
    docs, metas = retrieve_context(question, k=4)
    prompt, sorted_sources = build_rag_prompt(question, docs, metas)
    messages = [
        {"role": "system", "content": prompt},
    ]
    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL_NAME,
            messages=messages,
            temperature=0.2,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Error from Groq: {ex}")
    answer = completion.choices[0].message.content
    return JSONResponse({"text": answer, "sources": sorted_sources})


@app.post("/api/tts")
async def tts_endpoint(body: TTSBody):
    """Convert text to speech using local TTS server (Edge TTS) or ElevenLabs as fallback.

    The request must supply the text to convert. A voice mode may be
    supplied to select between Pro, Max or Kids voices. The audio is
    returned as a streaming response with MIME type ``audio/mpeg``.
    """
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    mode = body.mode or "pro"
    
    try:
        # Try local TTS server first
        try:
            # Determine voice based on mode
            voice = "gadis"  # Indonesian female voice
            if mode == "pro":
                voice = "ardhi"  # Indonesian male voice
            elif mode == "max":
                voice = "alloy"  # English voice
            
            # Local TTS API endpoint
            url = f"{TTS_BASE_URL}/v1/audio/speech"
            
            data = {
                "model": TTS_MODEL,
                "input": text,
                "voice": voice,
                "response_format": "mp3",
                "speed": 1.0
            }
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                
                return StreamingResponse(io.BytesIO(response.content), media_type="audio/mpeg")
        
        except Exception as local_error:
            # Fallback to ElevenLabs if available
            if not ELEVENLABS_API_KEY:
                raise HTTPException(
                    status_code=500, 
                    detail=f"Local TTS failed and no ElevenLabs API key configured: {local_error}"
                )
            
            voice_id = get_voice_id(mode)
            # Build payload for ElevenLabs API. We use the multilingual model
            # which supports Indonesian and adjust the stability/similarity to
            # create a calm, consistent voice. You can tune these numbers to
            # taste.
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.65,
                    "similarity_boost": 0.75,
                },
            }
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            }
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"ElevenLabs returned error: {response.text}",
                )
            
            return StreamingResponse(io.BytesIO(response.content), media_type="audio/mpeg")
            
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"TTS error: {ex}")


# ----------------------------------------------------------------------------
# Static file serving
# ----------------------------------------------------------------------------

from fastapi.staticfiles import StaticFiles  # imported late to avoid circular deps

# Serve the client folder. We construct the path relative to this file.
CLIENT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "client"))
if os.path.isdir(CLIENT_DIR):
    app.mount("/", StaticFiles(directory=CLIENT_DIR, html=True), name="client")