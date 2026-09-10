import unittest

from au_connect_recommendation_service.core.embedding_model import get_embedding_model


class EmbeddingModelTests(unittest.TestCase):
    def test_software_developer_is_more_similar_to_programmer_than_chef(self):
        model = get_embedding_model()
        embeddings = model.encode(
            [
                "query: Software Developer",
                "passage: Programmer who builds software applications",
                "passage: Professional chef working in a restaurant",
            ],
            normalize_embeddings=True,
        )

        self.assertEqual(embeddings.shape, (3, 384))
        programmer_similarity = embeddings[0] @ embeddings[1]
        chef_similarity = embeddings[0] @ embeddings[2]
        self.assertGreater(programmer_similarity, chef_similarity)


if __name__ == "__main__":
    unittest.main()
