"""recommender.py — Hybrid content + collaborative filtering engine.

Pipeline
========
1. **Filter** — score every movie by either collaborative cosine similarity
   (when the user has enough ratings) or by content cosine similarity to the
   user's inferred preference vector (cold-start fallback).
2. **Score** — blend the two scores with a tunable weight
   ``final = alpha * cf_score + (1 - alpha) * cbf_score``.
3. **Rank** — return the top-k, optionally excluding movies the user has
   already rated.

Filters out movies the user has already rated.

Item-item collaborative filtering: cosine similarity over rows of the
user-movie rating matrix. Cold-start threshold ``MIN_RATINGS_FOR_CF`` defaults
to 5 ratings.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import database as db

# ---------- tuning ----------

MIN_RATINGS_FOR_CF = 5
ALPHA_DEFAULT = 0.6  # weight on collaborative filter score


# ---------- data containers ----------

@dataclass
class ScoredMovie:
    movie_id: int
    title: str
    genres: str
    cf_score: float = 0.0
    cbf_score: float = 0.0
    final_score: float = 0.0
    rationale: str = ""

    def as_dict(self) -> dict:
        return {
            "movie_id": self.movie_id,
            "title": self.title,
            "genres": self.genres,
            "cf_score": round(self.cf_score, 4),
            "cbf_score": round(self.cbf_score, 4),
            "final_score": round(self.final_score, 4),
            "rationale": self.rationale,
        }


@dataclass
class PreferenceVector:
    """User preference vector used by the content-based filter."""
    genre_weights: dict[str, float] = field(default_factory=dict)
    favourite_titles: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "genre_weights": dict(
                sorted(self.genre_weights.items(), key=lambda kv: -kv[1])[:10]
            ),
            "favourite_titles": self.favourite_titles,
        }


# ---------- core engine ----------

class RecommendationEngine:
    """Hybrid recommendation engine.

    Holds an in-memory snapshot of the catalogue and ratings. ``refresh()``
    rebuilds the snapshot from SQLite — call it explicitly after new data
    is added (e.g. via the admin console or after a user rates a movie).
    """

    def __init__(self, alpha: float = ALPHA_DEFAULT):
        self.alpha = alpha
        self.movies_df: pd.DataFrame = pd.DataFrame()
        self.ratings_df: pd.DataFrame = pd.DataFrame()
        # matrices computed during refresh()
        self.user_item: pd.DataFrame = pd.DataFrame()
        self.item_content_matrix = None  # sparse
        self.item_ids: np.ndarray = np.array([])
        self.titles: dict[int, str] = {}
        self.genres: dict[int, str] = {}
        self._item_similarity = None  # sparse, normalised by row
        self.content_item_similarity = None  # sparse

    # ---------- lifecycle ----------

    def refresh(self) -> None:
        """Reload all data from SQLite and rebuild similarity matrices."""
        movies = db.list_movies(limit=10_000, sort_by="title")
        ratings_rows = db.app_state_get("ratings_cache_rows")
        # simpler: stream via paged list query
        # but for a 100k ratings cache it's fine to load all at once.
        with db.connect() as conn:
            ratings_df = pd.read_sql_query(
                "SELECT user_id, movie_id, score FROM ratings", conn
            )
        self.ratings_df = ratings_df

        self.movies_df = pd.DataFrame(movies)
        if self.movies_df.empty:
            self.item_ids = np.array([])
            return

        # Title / genre indexes
        self.titles = dict(zip(self.movies_df.movie_id, self.movies_df.title))
        self.genres = dict(zip(self.movies_df.movie_id, self.movies_df.genres))

        # ---- user-item matrix for collaborative filtering ----
        # Build a dense matrix aligned to self.item_ids so the item-item CF
        # similarity is over every catalogue movie, not only the rated ones.
        if not ratings_df.empty:
            user_ids = sorted(ratings_df["user_id"].unique().tolist())
            n_users = len(user_ids)
            n_items = len(self.item_ids)
            id_to_idx = {int(mid): i for i, mid in enumerate(self.item_ids)}
            user_vec = np.zeros((n_users, n_items), dtype=np.float32)
            uid_index = {uid: i for i, uid in enumerate(user_ids)}
            for u, m, s in ratings_df[["user_id", "movie_id", "score"]].itertuples(index=False):
                j = id_to_idx.get(int(m))
                if j is None:
                    continue
                user_vec[uid_index[int(u)], j] = float(s)
            self.user_item = pd.DataFrame(
                user_vec, index=user_ids, columns=self.item_ids
            )
        else:
            self.user_item = pd.DataFrame()

        # ---- content matrix: TF-IDF over genres ----
        # normalise MovieLens's '|' delimiter to spaces, keep '(no genres listed)' as-is
        corpus = [
            re.sub(r"\|", " ", g or "").strip() or "unknown"
            for g in self.movies_df.genres
        ]
        vectorizer = TfidfVectorizer(token_pattern=r"[A-Za-z][A-Za-z\-]+", lowercase=True)
        try:
            self.item_content_matrix = vectorizer.fit_transform(corpus)
        except ValueError:
            # all-empty corpus edge case
            from scipy.sparse import csr_matrix
            self.item_content_matrix = csr_matrix((len(corpus), 1))

        # ---- pre-computed similarity matrices ----
        # Item-item collaborative: cosine on columns (movies) of the user-item matrix
        if not self.user_item.empty:
            cf_matrix = cosine_similarity(self.user_item.T.values)
            self._item_similarity = _normalise_rows(cf_matrix)
        else:
            self._item_similarity = None

        # Item-item content similarity
        self.content_item_similarity = _normalise_rows(
            cosine_similarity(self.item_content_matrix)
        )

        # movie id sequence aligns with the matrix rows
        self.item_ids = self.movies_df.movie_id.to_numpy()

    # ---------- preference vector ----------

    def get_user_preference(self, user_id: int) -> PreferenceVector:
        """Infer a content-based preference vector for a user.

        Builds a genre-weight vector from the user's high-rated movies
        (score >= 4.0), and lists the titles that contributed most.
        """
        user_ratings = db.list_ratings_by_user(user_id, limit=1000)
        if not user_ratings:
            return PreferenceVector()

        weights: dict[str, float] = defaultdict(float)
        favs: list[tuple[str, float]] = []
        for r in user_ratings:
            score = float(r.get("score") or 0.0)
            if score < 4.0:
                continue
            for g in (r.get("genres") or "").split("|"):
                if not g:
                    continue
                weights[g] += score
            favs.append((r.get("title", ""), score))
        favs.sort(key=lambda kv: -kv[1])
        return PreferenceVector(
            genre_weights=dict(weights),
            favourite_titles=[t for t, _ in favs[:5]],
        )

    # ---------- top-k recommendations ----------

    def generate_recommendations(
        self,
        user_id: int,
        k: int = 10,
        alpha: float | None = None,
        exclude_rated: bool = True,
    ) -> list[dict]:
        """Return the top-k movies for a user, ranked by hybrid score.

        Falls back to content-based only when the user has fewer than
        ``MIN_RATINGS_FOR_CF`` ratings.
        """
        if self.movies_df.empty:
            return []

        alpha = self.alpha if alpha is None else alpha

        # Indexed lookup: row index by movie_id
        idx_by_id = {mid: i for i, mid in enumerate(self.item_ids)}

        rated_ids: set[int] = set()
        user_ratings = db.list_ratings_by_user(user_id, limit=10_000)
        for r in user_ratings:
            rated_ids.add(int(r["movie_id"]))

        # ---- cold start: pure content-based against genre preference ----
        if len(user_ratings) < MIN_RATINGS_FOR_CF:
            return self._cold_start_recommendations(
                user_ratings, k=k, exclude_rated=exclude_rated, rated_ids=rated_ids
            )

        # ---- warm user: hybrid ----
        cf_scores = self._cf_user_vector_scores(user_id, idx_by_id)
        cbf_scores = self._cbf_user_vector_scores(user_id, idx_by_id)

        scored: list[ScoredMovie] = []
        for mid in self.item_ids:
            idx = idx_by_id[mid]
            title = self.titles.get(mid, "")
            if exclude_rated and mid in rated_ids:
                continue
            cf = float(cf_scores[idx])
            cbf = float(cbf_scores[idx])
            final = alpha * cf + (1 - alpha) * cbf
            if final <= 0:
                continue
            scored.append(
                ScoredMovie(
                    movie_id=int(mid),
                    title=title,
                    genres=self.genres.get(int(mid), ""),
                    cf_score=cf,
                    cbf_score=cbf,
                    final_score=final,
                    rationale=(
                        f"similar to movies you rated ({cf:.2f}) and content match ({cbf:.2f})"
                    ),
                )
            )

        scored.sort(key=lambda s: -s.final_score)
        return [s.as_dict() for s in scored[:k]]

    # ---------- helpers ----------

    def _cold_start_recommendations(
        self,
        user_ratings: list[dict],
        k: int,
        exclude_rated: bool,
        rated_ids: set[int],
    ) -> list[dict]:
        """Use content similarity to the user's already-rated favourites."""
        if not user_ratings:
            # no ratings at all → surface trending movies with high ratings
            return self._most_popular_movies(k=k, exclude_rated=exclude_rated, rated_ids=rated_ids)

        idx_by_id = {mid: i for i, mid in enumerate(self.item_ids)}
        top_rated = sorted(user_ratings, key=lambda r: -float(r.get("score") or 0))[:3]
        candidate_scores: dict[int, float] = defaultdict(float)
        for r in top_rated:
            mid = int(r["movie_id"])
            if mid not in idx_by_id:
                continue
            i = idx_by_id[mid]
            sim = self.content_item_similarity[i]
            # sim is a dense row
            for j, s in enumerate(sim):
                c_mid = int(self.item_ids[j])
                if c_mid == mid:
                    continue
                candidate_scores[c_mid] += float(s) * float(r.get("score") or 0.0) / 5.0

        out: list[ScoredMovie] = []
        for mid, score in candidate_scores.items():
            if exclude_rated and mid in rated_ids:
                continue
            out.append(
                ScoredMovie(
                    movie_id=mid,
                    title=self.titles.get(mid, ""),
                    genres=self.genres.get(mid, ""),
                    cbf_score=score,
                    final_score=score,
                    rationale="because you rated similar titles highly",
                )
            )
        out.sort(key=lambda s: -s.final_score)
        return [s.as_dict() for s in out[:k]]

    def _most_popular_movies(
        self, k: int, exclude_rated: bool, rated_ids: set[int]
    ) -> list[dict]:
        # Bayesian-style popularity: IMDb's weighted rating uses m=10th-percentile
        # count; we use the raw average for simplicity.
        ranked = self.movies_df.sort_values(
            ["average_rating", "rating_count"], ascending=[False, False]
        )
        out: list[ScoredMovie] = []
        for _, row in ranked.iterrows():
            mid = int(row["movie_id"])
            if exclude_rated and mid in rated_ids:
                continue
            out.append(
                ScoredMovie(
                    movie_id=mid,
                    title=row["title"],
                    genres=row["genres"],
                    final_score=float(row["average_rating"]),
                    rationale="trending — high community rating",
                )
            )
        return [s.as_dict() for s in out[:k]]

    def _cf_user_vector_scores(
        self, user_id: int, idx_by_id: dict[int, int]
    ) -> np.ndarray:
        """Compute collaborative scores for every catalogue item for this user.

        Aligns to ``self.item_ids`` (every catalogue movie). Movies that
        have no ratings are treated as having a zero rating.
        """
        if self._item_similarity is None or user_id not in self.user_item.index:
            return np.zeros(len(self.item_ids))
        # Build a full-length rating vector aligned with item_ids
        user_col_idx_by_id = {col: i for i, col in enumerate(self.user_item.columns)}
        full_ratings = np.zeros(len(self.item_ids))
        for j, mid in enumerate(self.item_ids):
            if mid in user_col_idx_by_id:
                full_ratings[j] = float(
                    self.user_item.iloc[
                        self.user_item.index.get_loc(user_id), user_col_idx_by_id[mid]
                    ]
                )
        rated_mask = full_ratings > 0
        if not rated_mask.any():
            return np.zeros(len(self.item_ids))
        scores = np.zeros(len(self.item_ids))
        rated_indices = np.where(rated_mask)[0]
        # vectorised: for each rated item r in rated_indices:
        #   scores += ratings[r] * sims[r, :]
        for ri in rated_indices:
            scores += full_ratings[ri] * self._item_similarity[ri]
        scores = scores / max(1.0, float(rated_mask.sum()))
        return scores

    def _cbf_user_vector_scores(
        self, user_id: int, idx_by_id: dict[int, int]
    ) -> np.ndarray:
        """Compute content-based scores for every catalogue item for this user."""
        user_ratings = db.list_ratings_by_user(user_id, limit=10_000)
        if not user_ratings:
            return np.zeros(len(self.item_ids))
        # Build user preference vector as weighted average of rated movies
        rated_idx = []
        rated_score = []
        for r in user_ratings:
            mid = int(r["movie_id"])
            if mid in idx_by_id:
                rated_idx.append(idx_by_id[mid])
                rated_score.append(float(r["score"]))
        if not rated_idx:
            return np.zeros(len(self.item_ids))
        sub_matrix = self.item_content_matrix[rated_idx]  # sparse
        weights = np.array(rated_score).reshape(-1, 1)
        # weighted average row
        weighted = sub_matrix.multiply(weights).sum(axis=0)
        total = weights.sum()
        if total == 0:
            return np.zeros(len(self.item_ids))
        weighted = np.asarray(weighted) / total
        # cosine similarity between weighted user vector and every item
        from scipy.sparse import csr_matrix
        user_vec = csr_matrix(weighted)
        sim = cosine_similarity(user_vec, self.item_content_matrix)[0]
        return sim


# ---------- utilities ----------

def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    """Normalise each row of a dense matrix to unit length (so dot product =
    cosine similarity). Rows of all zeros stay zero."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


# ---------- module-scope singleton ----------

_engine: RecommendationEngine | None = None


def get_engine(alpha: float = ALPHA_DEFAULT) -> RecommendationEngine:
    """Lazy initialise (and cache) a RecommendationEngine.

    Used by the Streamlit app so we don't rebuild the matrices on every
    widget interaction. Caller can mutate alpha via the returned object.
    """
    global _engine
    if _engine is None:
        _engine = RecommendationEngine(alpha=alpha)
        _engine.refresh()
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so the next call rebuilds it from SQLite.

    Call this after any admin operation that mutates the movie catalogue
    so the new content similarity matrix is loaded.
    """
    global _engine
    _engine = None
