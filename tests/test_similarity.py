import threading
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from au_connect_recommendation_service.enums.account_status import AccountStatus
from au_connect_recommendation_service.models.education import Education
from au_connect_recommendation_service.models.experience import Experience
from au_connect_recommendation_service.models.user import User
from au_connect_recommendation_service.services import similarity as sim


def user(**fields):
    defaults = dict(id="one", username="one", title=None, about=None, location=None,
                    account_status=AccountStatus.ACTIVE, experience=[], education=[])
    return User(**(defaults | fields))


def experience(title, company="Company"):
    return Experience("job", title, "FULL_TIME", company, 1, 2020, None, None, True, "one")


def education(subject="", degree="", school=""):
    return Education("study", school, degree, subject, 1, 2016, 1, 2020, "one")


class SimilarityTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_and_empty_fields_do_not_load_model(self):
        with patch.object(sim, "get_embedding_model") as loader:
            self.assertEqual(await sim.calculate_profile_similarity(user(), user()), 0.0)
            loader.assert_not_called()
        result = sim.profile_similarity_breakdown(user(), user(), {})
        self.assertTrue(all(value is None for value in result["component_scores"].values()))
        self.assertEqual(result["available_weight_coverage"], 0)
        self.assertEqual(sum(result["effective_weights"].values()), 0)

    async def test_batch_unique_texts_prefix_normalization_and_offloading(self):
        main_thread = threading.get_ident()
        def encode(texts, **kwargs):
            self.assertNotEqual(threading.get_ident(), main_thread)
            return [[1.0, 0.0] for text in texts]
        model = Mock()
        model.encode.side_effect = encode
        first = user(title=" Developer ", about=" ", experience=[experience("DEVELOPER")],
                     education=[education("Computing")])
        second = user(title="developer", about="Software")
        with patch.object(sim, "get_embedding_model", return_value=model):
            embeddings = await sim.prepare_profile_embeddings([first, second])
            await sim.calculate_profile_similarity(first, second, embeddings)
            await sim.calculate_profile_similarity(second, first, embeddings)
        model.encode.assert_called_once_with(
            ["query: computing", "query: developer", "query: software"],
            normalize_embeddings=True, show_progress_bar=False,
        )

    async def test_async_two_argument_contract(self):
        with patch.object(sim, "get_embedding_model") as loader:
            loader.return_value.encode.return_value = [[1.0, 0.0]]
            score = await sim.calculate_profile_similarity(user(title="a"), user(title="a"))
        self.assertIsInstance(score, float)
        self.assertEqual(score, 1.0)

    def test_missing_reweighting_keeps_genuine_zero(self):
        first = user(title="a", location=" Bangkok ")
        second = user(title="b", location="BANGKOK")
        result = sim.profile_similarity_breakdown(first, second, {"a": [1, 0], "b": [0, 1]})
        self.assertEqual(result["component_scores"]["title"], 0.0)
        self.assertAlmostEqual(result["available_weight_coverage"], 0.35)
        self.assertAlmostEqual(result["final_score"], 0.10 / 0.35)
        self.assertAlmostEqual(sum(result["effective_weights"].values()), 1)
        sparse = sim.profile_similarity_breakdown(user(location="x"), user(location="X"), {})
        self.assertEqual(sparse["final_score"], 1)
        self.assertEqual(sparse["available_weight_coverage"], 0.1)

    def test_all_component_weights(self):
        first = user(title="a", about="a", experience=[experience("a")],
                     education=[education("a", "BSc", "school")], location="x")
        second = replace(first, about="b", location="y")
        result = sim.profile_similarity_breakdown(first, second, {"a": [1, 0], "b": [0, 1]})
        self.assertEqual(result["effective_weights"], sim.PROFILE_WEIGHTS)
        self.assertAlmostEqual(result["final_score"], 0.65)

    def test_exact_normalization_and_conservative_degrees(self):
        self.assertEqual(sim.location_similarity(user(location=" X "), user(location="x")), 1)
        self.assertIsNone(sim.location_similarity(user(location=" "), user(location="x")))
        self.assertEqual(sim.degree_similarity(" B.Sc. ", "Bachelor of Science"), 1)
        self.assertEqual(sim.degree_similarity("BSc", "Master of Science"), 0)
        self.assertEqual(sim.degree_similarity("Bachelor", "Bachelor of Science"), 0)
        self.assertEqual(sim.degree_similarity("Custom Degree", " custom degree "), 1)
        self.assertIsNone(sim.degree_similarity("", "BSc"))

    def test_symmetric_mean_best_deduplicates_titles_ignores_company(self):
        first = user(experience=[experience("a"), experience(" A "), experience("b")])
        second = user(experience=[experience("a", "Different company")])
        vectors = {"a": [1, 0], "b": [0, 1]}
        self.assertEqual(sim.experience_similarity(first, second, vectors), 0.75)
        self.assertEqual(sim.experience_similarity(second, first, vectors), 0.75)
        self.assertIsNone(sim.experience_similarity(user(experience=[experience(" ")]), second, vectors))

    def test_education_weights_and_record_pairing(self):
        vectors = {"computing": [1, 0], "cooking": [0, 1]}
        first = user(education=[education("computing", "BSc", "A")])
        second = user(education=[education("computing", "MSc", "B"),
                                 education("cooking", "BSc", "A")])
        # Best pair is .6, reverse best scores are .6 and .4: (.6 + .5) / 2.
        self.assertAlmostEqual(sim.education_similarity(first, second, vectors), 0.55)
        self.assertAlmostEqual(sim.education_similarity(second, first, vectors), 0.55)
        self.assertEqual(sim.education_similarity(first, replace(first, education=first.education * 2), vectors), 1)

    def test_study_subject_lists_and_partial_entries(self):
        vectors = {"a": [1, 0], "b": [0, 1]}
        first = user(education=[education("a"), education(" A "), education("b")])
        second = user(education=[education("a")])
        self.assertEqual(sim.education_similarity(first, second, vectors), 0.75)
        self.assertEqual(sim.education_similarity(user(education=[education(school=" A ")]),
                                                user(education=[education(school="a")]), {}), 1)
        self.assertIsNone(sim.education_similarity(user(education=[education()]), second, vectors))
        self.assertIsNone(sim.education_similarity(user(education=[education(degree="BSc")]), second, vectors))

    def test_semantic_score_bounds_and_missing(self):
        vectors = {"a": [1, 0], "b": [-1, 0], "c": [1.00000001, 0]}
        self.assertEqual(sim.semantic_text_similarity("a", "b", vectors), 0)
        self.assertEqual(sim.semantic_text_similarity("a", "c", vectors), 1)
        self.assertIsNone(sim.semantic_text_similarity(" ", "a", vectors))
        for title in vectors:
            result = sim.profile_similarity_breakdown(user(title="a"), user(title=title), vectors)
            self.assertGreaterEqual(result["final_score"], 0)
            self.assertLessEqual(result["final_score"], 1)


if __name__ == "__main__":
    unittest.main()
