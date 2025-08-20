// Frontend script for Baymax Assistant
//
// This script binds UI elements to API calls. When the user
// submits a question it optionally uses the RAG endpoint to augment
// the request with knowledge from kb.json and mb.json. It then calls
// the TTS endpoint to speak the response in the selected voice mode.

const API_BASE = ''; // relative base path; server and static are served from same origin

async function askBaymax() {
  const messageInput = document.getElementById('message');
  const useRag = document.getElementById('useRag').checked;
  const modeSelect = document.getElementById('mode');
  const askBtn = document.getElementById('askBtn');
  const responseDiv = document.getElementById('response');
  const sourcesDiv = document.getElementById('sources');
  const audioElem = document.getElementById('audio');

  const text = messageInput.value.trim();
  if (!text) {
    return;
  }

  askBtn.disabled = true;
  responseDiv.textContent = 'Memproses...';
  sourcesDiv.textContent = '';
  audioElem.src = '';

  try {
    // Determine endpoint
    const endpoint = useRag ? '/api/ask_rag' : '/api/chat';
    const body = JSON.stringify({ message: text });
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || 'Gagal mendapatkan jawaban');
    }
    const json = await res.json();
    const answer = json.text || '';
    const sources = json.sources || [];
    responseDiv.textContent = answer;
    if (sources.length > 0) {
      sourcesDiv.textContent = 'Sumber: ' + sources.join(', ');
    }
    // Call TTS
    const ttsRes = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: answer, mode: modeSelect.value })
    });
    if (!ttsRes.ok) {
      const errText = await ttsRes.text();
      throw new Error(errText || 'Gagal menghasilkan audio');
    }
    const buffer = await ttsRes.arrayBuffer();
    const blob = new Blob([buffer], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    audioElem.src = url;
    audioElem.play();
  } catch (e) {
    responseDiv.textContent = 'Terjadi kesalahan: ' + e.message;
  } finally {
    askBtn.disabled = false;
  }
}

document.getElementById('askBtn').addEventListener('click', askBaymax);