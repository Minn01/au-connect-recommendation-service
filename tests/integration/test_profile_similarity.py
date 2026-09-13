"""Run explicitly: uv run python -m unittest discover -s tests/integration -v."""
import json
import unittest

from au_connect_recommendation_service.enums.account_status import AccountStatus
from au_connect_recommendation_service.models.education import Education
from au_connect_recommendation_service.models.experience import Experience
from au_connect_recommendation_service.models.user import User
from au_connect_recommendation_service.services.similarity import (
    prepare_profile_embeddings,
    profile_similarity_breakdown,
)


def profile(name, title, about, subject, degree, school):
    return User(
        id=name, username=name, title=title, about=about, location="Bangkok",
        account_status=AccountStatus.ACTIVE,
        experience=[Experience(name, title, "FULL_TIME", name + " company",
                               1, 2020, None, None, True, name)],
        education=[Education(name, school, degree, subject, 1, 2016, 1, 2020, name)],
    )


class RealProfileSimilarityTests(unittest.IsolatedAsyncioTestCase):
    async def test_software_profile_ranks_above_culinary_profile(self):
        current = profile("current", "Software developer", "I build backend APIs and web applications.",
                          "Computer science", "BSc", "Technology University")
        software = profile("software", "Software engineer", "I develop software services and web systems.",
                           "Software engineering", "Bachelor of Science", "Engineering University")
        culinary = profile("culinary", "Restaurant chef", "I prepare meals and create restaurant menus.",
                           "Culinary arts", "Diploma", "Culinary School")
        embeddings = await prepare_profile_embeddings([current, software, culinary])
        results = {candidate.username: profile_similarity_breakdown(current, candidate, embeddings)
                   for candidate in (software, culinary)}
        print("\nProfile similarity breakdowns (scores are not probabilities):")
        print(json.dumps(results, indent=2))
        self.assertGreater(results["software"]["final_score"], results["culinary"]["final_score"])


if __name__ == "__main__":
    unittest.main()
