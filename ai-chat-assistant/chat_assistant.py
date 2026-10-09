"""
AI Chat Assistant - Proyek Akhir
Penulis : ForYuu Creative (NIM 2301100037)

Asisten ini menjawab pertanyaan berdasarkan DATA SENDIRI (data/knowledge.json).

Dua mode:
1. OFFLINE  -> tanpa internet / API key. Mencari jawaban paling relevan
               dari knowledge base memakai TF-IDF + cosine similarity.
2. LLM      -> jika ANTHROPIC_API_KEY tersedia, potongan data yang relevan
               dikirim sebagai konteks ke model Claude agar jawaban lebih natural
               (pola ini disebut RAG: Retrieval-Augmented Generation).

Jalankan:  python chat_assistant.py
"""

import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "knowledge.json"
MODEL_NAME = "claude-sonnet-5-5"

STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "ini", "itu", "dengan", "untuk", "pada",
    "adalah", "apa", "siapa", "bagaimana", "berapa", "kapan", "dimana", "mengapa",
    "kenapa", "saya", "aku", "kamu", "anda", "dia", "nya", "atau", "juga", "akan",
    "ada", "bisa", "apakah", "tolong", "dong", "ya", "sebuah", "oleh", "dalam",
    "the", "is", "a", "of", "to", "and",
}

try:  # .env bersifat opsional
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass


# --------------------------------------------------------------------------
# 1. Memuat data & membangun indeks pencarian (TF-IDF)
# --------------------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def load_knowledge(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[ERROR] File data tidak ditemukan: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class KnowledgeIndex:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.docs = [tokenize(e["judul"] + " " + e["isi"] + " " + " ".join(e.get("kata_kunci", [])))
                     for e in entries]
        n = len(self.docs)
        df = Counter()
        for doc in self.docs:
            df.update(set(doc))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vectors = [self._vectorize(doc) for doc in self.docs]

    def _vectorize(self, tokens: list[str]) -> dict:
        tf = Counter(tokens)
        vec = {t: c * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, query: str, k: int = 3, min_score: float = 0.12):
        qvec = self._vectorize(tokenize(query))
        scored = []
        for entry, vec in zip(self.entries, self.vectors):
            score = sum(w * vec.get(t, 0.0) for t, w in qvec.items())
            if score >= min_score:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


# --------------------------------------------------------------------------
# 2. Mode LLM (opsional)
# --------------------------------------------------------------------------
def build_llm_client():
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        print("[info] Paket 'anthropic' belum terpasang -> memakai mode offline.")
        return None
    return anthropic.Anthropic(api_key=key)


def ask_llm(client, persona: str, context: str, history: list[dict]) -> str:
    system = (
        f"{persona}\n\n"
        "Jawab dalam bahasa Indonesia yang singkat dan ramah. "
        "Gunakan HANYA informasi pada KONTEKS di bawah. "
        "Jika jawabannya tidak ada di konteks, katakan dengan jujur bahwa kamu belum punya datanya.\n\n"
        f"KONTEKS:\n{context or '(tidak ada data yang relevan)'}"
    )
    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=500,
        system=system,
        messages=history[-10:],
    )
    return response.content[0].text


# --------------------------------------------------------------------------
# 3. Loop percakapan
# --------------------------------------------------------------------------
HELP_TEXT = """Perintah:
  /help    tampilkan bantuan
  /topik   lihat topik yang saya ketahui
  /reset   hapus riwayat percakapan
  /exit    keluar"""


def main() -> None:
    data = load_knowledge(DATA_FILE)
    index = KnowledgeIndex(data["entries"])
    client = build_llm_client()
    mode = "LLM (Claude + data sendiri)" if client else "OFFLINE (TF-IDF)"
    name = data.get("nama_asisten", "Asisten")

    print("=" * 60)
    print(f" {name}  |  Mode: {mode}")
    print(" Ketik /help untuk bantuan, /exit untuk keluar.")
    print("=" * 60)
    print(data.get("sapaan", "Halo! Ada yang bisa saya bantu?"))

    history: list[dict] = []
    while True:
        try:
            user = input("\nKamu  : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + name + ": Sampai jumpa!")
            break
        if not user:
            continue

        cmd = user.lower()
        if cmd in ("/exit", "/keluar", "exit", "quit"):
            print(f"{name}: Sampai jumpa! Semangat belajarnya ")
            break
        if cmd == "/help":
            print(HELP_TEXT)
            continue
        if cmd == "/reset":
            history.clear()
            print(f"{name}: Riwayat percakapan dihapus.")
            continue
        if cmd == "/topik":
            for e in data["entries"]:
                print(f"  - {e['judul']}")
            continue

        results = index.search(user)
        history.append({"role": "user", "content": user})

        if client:
            context = "\n\n".join(f"[{e['judul']}]\n{e['isi']}" for _, e in results)
            try:
                reply = ask_llm(client, data.get("persona", ""), context, history)
            except Exception as exc:  # jaringan / kunci salah, dsb.
                reply = f"(Gagal memanggil LLM: {exc}). Coba cek API key atau koneksi internet."
        elif results:
            best_score, best = results[0]
            reply = best["isi"]
            if len(results) > 1:
                lain = ", ".join(e["judul"] for _, e in results[1:])
                reply += f"\n(Topik terkait: {lain})"
        else:
            reply = data.get("fallback", "Maaf, saya belum punya data untuk pertanyaan itu.")

        history.append({"role": "assistant", "content": reply})
        print(f"\n{name}: {reply}")


if __name__ == "__main__":
    main()
