"""Semantic search using ChromaDB and local Ollama embeddings."""

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any

import chromadb
import httpx
from opentelemetry import trace

from observability import get_tracer

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSION = 384
BATCH_SIZE = 64


class EmbeddingCache:
    """LRU cache for embedding vectors."""

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _key(model: str, text: str) -> str:
        return hashlib.md5(f"{model}:{text}".encode()).hexdigest()

    def get(self, model: str, text: str) -> list[float] | None:
        k = self._key(model, text)
        if k in self._cache:
            self._hits += 1
            self._cache.move_to_end(k)
            return self._cache[k]
        self._misses += 1
        return None

    def put(self, model: str, text: str, embedding: list[float]) -> None:
        k = self._key(model, text)
        if k in self._cache:
            self._cache.move_to_end(k)
        self._cache[k] = embedding
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def __len__(self) -> int:
        return len(self._cache)


class OllamaEmbeddingFunction(chromadb.EmbeddingFunction[list[str]]):
    """ChromaDB-compatible embedding function using a local Ollama server."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "all-minilm",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._cache = EmbeddingCache(max_size=128)

    def __call__(self, input: list[str]) -> list[list[float]]:
        if not input:
            return []

        tracer = get_tracer()
        with tracer.start_as_current_span("embedding.ollama") as span:
            span.set_attribute("embedding.model", self._model)
            span.set_attribute("embedding.texts_count", len(input))

            results: list[tuple[int, list[float]]] = []
            uncached: list[tuple[int, str]] = []

            for idx, text in enumerate(input):
                cached = self._cache.get(self._model, text)
                if cached is not None:
                    results.append((idx, cached))
                else:
                    uncached.append((idx, text))

            cache_hits = len(input) - len(uncached)
            span.set_attribute("embedding.cache_hits", cache_hits)
            span.set_attribute("embedding.cache_misses", len(uncached))

            if uncached:
                batch_count = 0
                for batch_start in range(0, len(uncached), BATCH_SIZE):
                    batch = uncached[batch_start:batch_start + BATCH_SIZE]
                    batch_texts = [t for _, t in batch]
                    batch_count += 1
                    try:
                        t0 = time.time()
                        resp = httpx.post(
                            f"{self._base_url}/api/embed",
                            json={"model": self._model, "input": batch_texts},
                            timeout=120,
                        )
                        resp.raise_for_status()
                        span.set_attribute("embedding.api_latency_ms", int((time.time() - t0) * 1000))
                    except httpx.ConnectError:
                        logger.warning(
                            "Ollama not reachable at %s — returning empty embeddings",
                            self._base_url,
                        )
                        span.set_attribute("embedding.error", "connection_error")
                        return []

                    data = resp.json()
                    embeddings = data["embeddings"]
                    for i, (orig_idx, text) in enumerate(batch):
                        emb = embeddings[i]
                        self._cache.put(self._model, text, emb)
                        results.append((orig_idx, emb))

                span.set_attribute("embedding.batch_count", batch_count)

            results.sort(key=lambda x: x[0])
            return [emb for _, emb in results]

    def clear_cache(self) -> None:
        self._cache.clear()

    @property
    def cache_stats(self) -> dict[str, int]:
        return {
            "size": len(self._cache),
            "hits": self._cache.hits,
            "misses": self._cache.misses,
        }


class SemanticSearch:
    """Semantic search backed by ChromaDB with Ollama embeddings."""

    def __init__(
        self,
        persist_dir: str,
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "all-minilm",
    ) -> None:
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embed_fn = OllamaEmbeddingFunction(
            base_url=ollama_base_url, model=ollama_model,
        )

    @property
    def embed_fn(self) -> OllamaEmbeddingFunction:
        return self._embed_fn

    def _get_or_create_collection(self, name: str) -> chromadb.Collection:
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def collection_exists(self, name: str) -> bool:
        try:
            self._client.get_collection(name)
            return True
        except Exception:
            return False

    def add_documents(self, collection_name: str, docs: list[dict]) -> None:
        if not docs:
            return
        collection = self._get_or_create_collection(collection_name)

        ids = [d["id"] for d in docs]
        texts = [d["text"] for d in docs]
        metadatas = []
        for d in docs:
            meta = {}
            for key in ("file_path", "section", "symbol", "kind", "start_line", "heading"):
                if key in d and d[key]:
                    meta[key] = str(d[key])
            metadatas.append(meta)

        for i in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[i:i + BATCH_SIZE]
            batch_texts = texts[i:i + BATCH_SIZE]
            batch_meta = metadatas[i:i + BATCH_SIZE]
            collection.upsert(ids=batch_ids, documents=batch_texts, metadatas=batch_meta)

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 10,
        where: dict | None = None,
    ) -> list[dict]:
        if not query_text.strip():
            return []

        tracer = get_tracer()
        with tracer.start_as_current_span("search.semantic.query") as span:
            span.set_attribute("search.collection", collection_name)
            span.set_attribute("search.n_results_requested", n_results)

            try:
                collection = self._client.get_collection(
                    name=collection_name,
                    embedding_function=self._embed_fn,
                )
            except Exception:
                span.set_attribute("search.collection_found", False)
                return []

            count = collection.count()
            if count == 0:
                span.set_attribute("search.collection_count", 0)
                return []

            span.set_attribute("search.collection_count", count)

            kwargs: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": min(n_results, count),
            }
            if where:
                kwargs["where"] = where

            try:
                t0 = time.time()
                results = collection.query(**kwargs)
                span.set_attribute("search.query_latency_ms", int((time.time() - t0) * 1000))
            except Exception as e:
                logger.warning("Semantic query failed: %s", e)
                span.set_attribute("search.error", str(e)[:200])
                return []

            if not results or not results["documents"] or not results["documents"][0]:
                span.set_attribute("search.results_count", 0)
                return []

            output: list[dict] = []
            for i, doc in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 1.0
                output.append({
                    "text": doc,
                    "file_path": meta.get("file_path", ""),
                    "section": meta.get("section", ""),
                    "symbol": meta.get("symbol", ""),
                    "score": round(1.0 - distance, 4),
                    **{k: v for k, v in meta.items() if k not in ("file_path", "section", "symbol")},
                })

            span.set_attribute("search.results_count", len(output))
            return output

    def delete_collection(self, name: str) -> None:
        try:
            self._client.delete_collection(name)
        except Exception:
            pass

    def count(self, collection_name: str) -> int:
        try:
            return self._client.get_collection(collection_name).count()
        except Exception:
            return 0
