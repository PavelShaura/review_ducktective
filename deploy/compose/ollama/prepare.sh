#!/bin/sh
# Готовит модель эмбеддингов: базовая тянется из реестра, рабочая — её копия
# в q8_0 с числом потоков по ядрам машины. Повторный запуск ничего
# не качает и не пересобирает.
set -eu

BASE="${OLLAMA_EMBEDDING_BASE_MODEL:-nomic-embed-text}"
MODEL="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text-q8}"
THREADS="${OLLAMA_EMBEDDING_THREADS:-$(nproc)}"

if ollama show "$MODEL" >/dev/null 2>&1; then
  echo "модель $MODEL уже собрана"
  exit 0
fi

ollama pull "$BASE"
printf 'FROM %s\nPARAMETER num_thread %s\n' "$BASE" "$THREADS" > /tmp/Modelfile
ollama create "$MODEL" --quantize q8_0 -f /tmp/Modelfile
echo "модель $MODEL собрана: q8_0, потоков $THREADS"
