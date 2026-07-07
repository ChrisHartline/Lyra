from __future__ import annotations

import numpy as np
from lyra.embeddings import EmbeddingService, cosine_similarity


class FakeMiniLM:
    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        out = []
        for text in texts:
            t = text.lower()
            v = np.zeros(384, dtype=np.float32)
            if "quantum" in t:
                v[0] += 1.0
            if "qnn" in t or "ansatz" in t:
                v[1] += 0.8
                # Keep qnn/ansatz semantically near other quantum phrases.
                v[0] += 0.6
            if "pizza" in t:
                v[200] += 1.0
            if not v.any():
                v[10] = 0.1
            n = np.linalg.norm(v)
            if n:
                v = v / n
            out.append(v)
        return np.array(out)


def test_a2_embedding_shape_and_semantic_signal(monkeypatch):
    svc = EmbeddingService()
    monkeypatch.setattr(svc, "_get_model", lambda: FakeMiniLM())

    vecs = svc.embed_texts(["quantum circuit", "QNN ansatz", "pizza recipe"])
    assert vecs.shape == (3, 384)

    qc, qnn, pizza = vecs
    assert cosine_similarity(qc, qnn) > cosine_similarity(qc, pizza)
