#!/usr/bin/env bash
# User-space Ollama install (no sudo) + pull a small instruct model for local agent runs.
#
#   bash scripts/setup_local_llm.sh [model]          default model: qwen2.5:7b-instruct
#
# Installs to ~/.local/ollama (binary + bundled CUDA libs), stores models in
# ~/.local/ollama/models, starts `ollama serve` on 127.0.0.1:11434 if it is not running,
# and pulls the model. Downloads: ~1.5 GB runtime + ~4.7 GB model (7B, Q4_K_M).
set -euo pipefail
MODEL="${1:-qwen2.5:7b-instruct}"
PREFIX="$HOME/.local/ollama"
export OLLAMA_MODELS="$PREFIX/models"
export OLLAMA_HOST="127.0.0.1:11434"
mkdir -p "$PREFIX" "$OLLAMA_MODELS" "$PREFIX/logs"

if [ ! -x "$PREFIX/bin/ollama" ]; then
  echo "[setup] downloading ollama runtime (~1.5 GB) ..."
  curl -L --fail --progress-bar -o "$PREFIX/ollama-linux-amd64.tar.zst" https://ollama.com/download/ollama-linux-amd64.tar.zst
  echo "[setup] extracting ..."
  tar --zstd -xf "$PREFIX/ollama-linux-amd64.tar.zst" -C "$PREFIX"
  rm -f "$PREFIX/ollama-linux-amd64.tar.zst"
  ls -la "$PREFIX/bin" "$PREFIX/lib/ollama" | head -20
fi
export PATH="$PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$PREFIX/lib/ollama:${LD_LIBRARY_PATH:-}"

if ! curl -s --max-time 2 "http://$OLLAMA_HOST/api/version" >/dev/null; then
  echo "[setup] starting ollama serve (log: $PREFIX/logs/serve.log)"
  nohup "$PREFIX/bin/ollama" serve > "$PREFIX/logs/serve.log" 2>&1 &
  for _ in $(seq 1 30); do
    sleep 1
    curl -s --max-time 2 "http://$OLLAMA_HOST/api/version" >/dev/null && break
  done
fi
curl -s "http://$OLLAMA_HOST/api/version"; echo
echo "[setup] pulling $MODEL ..."
"$PREFIX/bin/ollama" pull "$MODEL"
"$PREFIX/bin/ollama" list
echo "[setup] done. OpenAI-compatible endpoint: http://$OLLAMA_HOST/v1"
