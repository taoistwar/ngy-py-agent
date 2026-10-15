import math
from collections.abc import Iterable
from typing import Self


class Vector:
    def __init__(self, components: Iterable[float]) -> None:
        self.components: list[float] = list(components)
        self.dim: int = len(self.components)

    def _ensure_same_dim(self, other: Self) -> None:
        """Reject silent truncation: zip() would drop elements on dim mismatch."""
        if self.dim != other.dim:
            raise ValueError(f"dimension mismatch: {self.dim} != {other.dim}")

    def __add__(self, other: Self) -> Self:
        self._ensure_same_dim(other)
        return type(self)([a + b for a, b in zip(self.components, other.components)])

    def __sub__(self, other: Self) -> Self:
        self._ensure_same_dim(other)
        return type(self)([a - b for a, b in zip(self.components, other.components)])

    def dot(self, other: Self) -> float:
        self._ensure_same_dim(other)
        return sum(a * b for a, b in zip(self.components, other.components))

    def magnitude(self) -> float:
        """模长"""
        # math.hypot scales internally: avoids overflow/underflow from x ** 2.
        return math.hypot(*self.components)

    def normalize(self) -> Self:
        mag = self.magnitude()
        if mag == 0.0:
            raise ValueError("cannot normalize a zero vector")
        return type(self)([x / mag for x in self.components])

    def cosine_similarity(self, other: Self) -> float:
        self._ensure_same_dim(other)
        denom = self.magnitude() * other.magnitude()
        if denom == 0.0:
            raise ValueError("cosine similarity is undefined for zero vectors")
        return self.dot(other) / denom

    def __repr__(self) -> str:
        return f"Vector({self.components})"


a = Vector([1, 2, 3])
b = Vector([4, 5, 6])

print(f"a + b = {a + b}")
print(f"a · b = {a.dot(b)}")
print(f"|a| = {a.magnitude():.4f}")
print(f"cosine similarity = {a.cosine_similarity(b):.4f}")
