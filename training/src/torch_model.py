"""The PyTorch candidate: a small text classifier with the same interface as a scikit-learn model
(fit, predict, predict_proba, classes_), so train.py, MLflow and the gate treat both families the same way.

Model: words and word pairs → ids (vocabulary from the training data) → EmbeddingBag (the average of
their vectors) → one linear layer → one score per dispute type. A few hundred thousand parameters;
trains on CPU in seconds.
"""

from collections import Counter

import numpy as np
import torch
from torch import nn


def tokens(text):
    words = text.lower().split()
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


class _Net(nn.Module):
    def __init__(self, vocab_size, dim, n_classes):
        super().__init__()
        self.embedding = nn.EmbeddingBag(vocab_size, dim, mode="mean")
        self.out = nn.Linear(dim, n_classes)

    def forward(self, ids, offsets):
        return self.out(self.embedding(ids, offsets))


class TorchTextClassifier:
    framework = "pytorch"

    def __init__(self, dim=64, epochs=8, lr=0.02, min_count=2, batch_size=64, seed=0):
        self.dim, self.epochs, self.lr, self.min_count, self.batch_size, self.seed = dim, epochs, lr, min_count, batch_size, seed

    def get_params(self):
        return {"dim": self.dim, "epochs": self.epochs, "lr": self.lr, "min_count": self.min_count}

    def _encode(self, texts):
        """Concatenated token ids + where each text starts (the EmbeddingBag input format). 0 = unknown token."""
        ids, offsets = [], []
        for text in texts:
            offsets.append(len(ids))
            ids.extend([self.vocab_.get(t, 0) for t in tokens(text)] or [0])
        return torch.tensor(ids, dtype=torch.long), torch.tensor(offsets, dtype=torch.long)

    def fit(self, texts, labels):
        torch.manual_seed(self.seed)
        texts, labels = list(texts), np.asarray(list(labels))
        counts = Counter(t for text in texts for t in tokens(text))
        self.vocab_ = {t: i + 1 for i, t in enumerate(sorted(t for t, c in counts.items() if c >= self.min_count))}
        self.classes_ = np.array(sorted(set(labels)))
        y = torch.tensor(np.searchsorted(self.classes_, labels), dtype=torch.long)

        self.net_ = _Net(len(self.vocab_) + 1, self.dim, len(self.classes_))
        optimiser = torch.optim.Adam(self.net_.parameters(), lr=self.lr)
        loss_fn = nn.CrossEntropyLoss()
        rng = np.random.default_rng(self.seed)
        self.net_.train()
        for _ in range(self.epochs):
            order = rng.permutation(len(texts))
            for start in range(0, len(order), self.batch_size):
                batch = order[start:start + self.batch_size]
                ids, offsets = self._encode([texts[i] for i in batch])
                optimiser.zero_grad()
                loss = loss_fn(self.net_(ids, offsets), y[batch])
                loss.backward()
                optimiser.step()
        self.net_.eval()
        return self

    def predict_proba(self, texts):
        with torch.no_grad():
            ids, offsets = self._encode(list(texts))
            return torch.softmax(self.net_(ids, offsets), dim=1).numpy()

    def predict(self, texts):
        return self.classes_[self.predict_proba(texts).argmax(axis=1)]
