from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TypedDict

from starlette.concurrency import run_in_threadpool

from au_connect_recommendation_service.core.embedding_model import get_embedding_model
from au_connect_recommendation_service.models.user import User

# weight of profile attributes which affect the final score
PROFILE_WEIGHTS = {
    "title": 0.25,
    "about": 0.25,
    "experience": 0.25,
    "education": 0.15,
    "location": 0.10,
}
EDUCATION_WEIGHTS = {"field_of_study": 0.60, "degree": 0.20, "school": 0.20}
# Only explicit spelling/abbreviation variants; no inferred degree levels.
DEGREE_ALIASES = {
    "bsc": "bachelor of science",
    "b.sc.": "bachelor of science",
    "msc": "master of science",
    "m.sc.": "master of science",
    "phd": "doctor of philosophy",
    "ph.d.": "doctor of philosophy",
}
Embeddings = Mapping[str, Sequence[float]]


class ScoreBreakdown(TypedDict):
    component_scores: dict[str, float | None]
    effective_weights: dict[str, float]
    available_weight_coverage: float
    final_score: float


def normalize_text(text: str | None) -> str:
    return (text or "").strip().casefold()


def _unique_texts(texts: Iterable[str | None]) -> list[str]:
    normalized = {normalize_text(text) for text in texts}
    return sorted(normalized - {""})


def _encode_texts(texts: list[str]) -> Embeddings:
    # E5 uses query: on both sides for symmetric similarity (see its model card).
    vectors = get_embedding_model().encode(
        [f"query: {text}" for text in texts],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return dict(zip(texts, vectors, strict=True))


async def prepare_profile_embeddings(users: Iterable[User]) -> Embeddings:
    """Encode each nonempty text once per request, including the current user's."""
    texts = []
    for user in users:
        texts.extend([user.title, user.about])
        texts.extend(entry.title for entry in user.experience)
        texts.extend(entry.field_of_study for entry in user.education)
    unique = _unique_texts(texts)
    if not unique:
        return {}
    # Both the cached loader and synchronous inference run outside the event loop.
    return await run_in_threadpool(_encode_texts, unique)


def semantic_text_similarity(
    first: str | None, second: str | None, embeddings: Embeddings,
) -> float | None:
    first, second = normalize_text(first), normalize_text(second)
    if not first or not second:
        return None
    # Normalized embeddings make the dot product cosine similarity. Clip negative
    # values to zero: this score measures positive similarity, not probability.
    score = sum(a * b for a, b in zip(embeddings[first], embeddings[second], strict=True))
    return max(0.0, min(1.0, float(score)))


def _exact_similarity(first: str | None, second: str | None) -> float | None:
    first, second = normalize_text(first), normalize_text(second)
    return float(first == second) if first and second else None


def location_similarity(current_user: User, candidate: User) -> float | None:
    return _exact_similarity(current_user.location, candidate.location)


def title_similarity(current_user: User, candidate: User, embeddings: Embeddings) -> float | None:
    return semantic_text_similarity(current_user.title, candidate.title, embeddings)


def about_similarity(current_user: User, candidate: User, embeddings: Embeddings) -> float | None:
    return semantic_text_similarity(current_user.about, candidate.about, embeddings)


def _mean_best_similarity[T](
    first: Sequence[T], second: Sequence[T], compare: Callable[[T, T], float | None],
) -> float | None:
    if not first or not second:
        return None
    scores = [[compare(a, b) for b in second] for a in first]

    def mean_best(rows):
        best = []
        for row in rows:
            available = [score for score in row if score is not None]
            if available:
                best.append(max(available))
        return sum(best) / len(best) if best else None

    # Average each item's best match in both directions so extra entries matter
    # equally on either profile. Rows without comparable information are omitted.
    forward = mean_best(scores)
    backward = mean_best(zip(*scores))
    if forward is None or backward is None:
        return None
    return (forward + backward) / 2


def experience_similarity(current_user: User, candidate: User, embeddings: Embeddings) -> float | None:
    return _mean_best_similarity(
        _unique_texts(entry.title for entry in current_user.experience),
        _unique_texts(entry.title for entry in candidate.experience),
        lambda a, b: semantic_text_similarity(a, b, embeddings),
    )


def field_of_study_similarity(
    first: str | None, second: str | None, embeddings: Embeddings,
) -> float | None:
    return semantic_text_similarity(first, second, embeddings)


def _normalize_degree(degree: str | None) -> str:
    normalized = normalize_text(degree)
    return DEGREE_ALIASES.get(normalized, normalized)


def degree_similarity(first: str | None, second: str | None) -> float | None:
    return _exact_similarity(_normalize_degree(first), _normalize_degree(second))


def _weighted_breakdown(
    scores: dict[str, float | None], weights: dict[str, float],
) -> ScoreBreakdown:
    coverage = sum(weights[name] for name, score in scores.items() if score is not None)
    effective = {
        name: weights[name] / coverage if score is not None and coverage else 0.0
        for name, score in scores.items()
    }
    final = sum(score * effective[name] for name, score in scores.items() if score is not None)
    return {
        "component_scores": scores,
        "effective_weights": effective,
        "available_weight_coverage": coverage,
        "final_score": max(0.0, min(1.0, final)),
    }


def education_similarity(current_user: User, candidate: User, embeddings: Embeddings) -> float | None:
    def entries(user):
        # Deduplicate complete records, keeping subjects, degrees and schools paired.
        return sorted({
            (normalize_text(entry.field_of_study), _normalize_degree(entry.degree),
             normalize_text(entry.school))
            for entry in user.education
            if any(normalize_text(value) for value in
                   (entry.field_of_study, entry.degree, entry.school))
        })

    def compare(first, second):
        scores = {
            "field_of_study": field_of_study_similarity(first[0], second[0], embeddings),
            "degree": degree_similarity(first[1], second[1]),
            "school": _exact_similarity(first[2], second[2]),
        }
        breakdown = _weighted_breakdown(scores, EDUCATION_WEIGHTS)
        return breakdown["final_score"] if breakdown["available_weight_coverage"] else None

    return _mean_best_similarity(entries(current_user), entries(candidate), compare)


def profile_similarity_breakdown(
    current_user: User, candidate: User, embeddings: Embeddings,
) -> ScoreBreakdown:
    """Internal diagnostics, not an API response or a probability.

    Missing-data reweighting can give sparse profiles high scores despite limited
    evidence. Coverage is the available fraction of the original component weights;
    it does not measure completeness within experience or education records.
    """
    return _weighted_breakdown({
        "title": title_similarity(current_user, candidate, embeddings),
        "about": about_similarity(current_user, candidate, embeddings),
        "experience": experience_similarity(current_user, candidate, embeddings),
        "education": education_similarity(current_user, candidate, embeddings),
        "location": location_similarity(current_user, candidate),
    }, PROFILE_WEIGHTS)


async def calculate_profile_similarity(
    current_user: User, candidate: User, embeddings: Embeddings | None = None,
) -> float:
    if embeddings is None:
        embeddings = await prepare_profile_embeddings([current_user, candidate])
    return profile_similarity_breakdown(current_user, candidate, embeddings)["final_score"]
