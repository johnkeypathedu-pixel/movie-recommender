"""Core domain classes for the Movie Recommendation System prototype."""

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class Movie:
    """A movie in the catalogue."""

    movie_id: str
    title: str
    genres: list[str]
    year: int
    ratings: list[float] = field(default_factory=list)
    watch_count: int = 0

    def add_rating(self, score: float) -> None:
        """Store a validated rating and update the movie's aggregate data."""
        if not 1 <= score <= 5:
            raise ValueError("Rating must be between 1 and 5.")
        self.ratings.append(float(score))

    @property
    def average_rating(self) -> float:
        return sum(self.ratings) / len(self.ratings) if self.ratings else 0.0


@dataclass
class User:
    """A registered user and their interaction history."""

    user_id: str
    name: str
    ratings: dict[str, float] = field(default_factory=dict)
    watch_history: list[str] = field(default_factory=list)

    def rate_movie(self, movie_id: str, score: float) -> None:
        """Record the user's rating for a movie."""
        if not 1 <= score <= 5:
            raise ValueError("Rating must be between 1 and 5.")
        self.ratings[movie_id] = float(score)

    def get_user_history(self) -> list[str]:
        """Return movie IDs watched by the user, newest first."""
        return list(reversed(self.watch_history))


class RecommendationEngine:
    """Searches the catalogue and ranks movies using simple preference signals."""

    def __init__(self, catalogue: Iterable[Movie]):
        self.catalogue = list(catalogue)

    def search_movies(self, query: str) -> list[Movie]:
        """Return title or genre matches for a search query."""
        query = query.strip().lower()
        if not query:
            return self.catalogue
        return [
            movie
            for movie in self.catalogue
            if query in movie.title.lower()
            or any(query in genre.lower() for genre in movie.genres)
        ]

    def recommend(self, user: User, limit: int = 5) -> list[Movie]:
        """Rank unseen movies by genre preference, rating, and popularity."""
        genre_scores: dict[str, float] = {}
        for movie_id, rating in user.ratings.items():
            movie = next((item for item in self.catalogue if item.movie_id == movie_id), None)
            if movie:
                for genre in movie.genres:
                    genre_scores[genre] = genre_scores.get(genre, 0) + rating

        unseen = [movie for movie in self.catalogue if movie.movie_id not in user.ratings]

        def score(movie: Movie) -> tuple[float, float, int]:
            preference = sum(genre_scores.get(genre, 0) for genre in movie.genres)
            return preference, movie.average_rating, movie.watch_count

        return sorted(unseen, key=score, reverse=True)[:limit]


def demo_catalogue() -> list[Movie]:
    """Return reproducible demo data for the prototype."""
    return [
        Movie("M001", "The Last Horizon", ["Sci-Fi", "Adventure"], 2024, [4, 5, 4], 120),
        Movie("M002", "Midnight in Kyoto", ["Drama", "Romance"], 2023, [5, 4, 5], 96),
        Movie("M003", "Codebreakers", ["Thriller", "Drama"], 2022, [4, 4, 3], 150),
        Movie("M004", "Laugh Track", ["Comedy"], 2024, [3, 4, 4], 180),
        Movie("M005", "Wild Planet", ["Documentary"], 2021, [5, 5, 4], 210),
        Movie("M006", "Neon Racers", ["Action", "Adventure"], 2023, [4, 3, 4], 175),
    ]
