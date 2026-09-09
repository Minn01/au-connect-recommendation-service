from au_connect_recommendation_service.models.user import User

async def calculate_profile_similarity(
    current_user: User,
    candidate: User,
) -> float:
    location_score = location_similarity(
        current_user,
        candidate,
    )

    title_score = title_similarity(
        current_user,
        candidate,
    )

    experience_score = experience_similarity(
        current_user,
        candidate,
    )

    education_score = education_similarity(
        current_user,
        candidate,
    )

    return (
        location_score * 0.30
        + title_score * 0.30
        + experience_score * 0.25
        + education_score * 0.15
    )

def location_similarity(
    current_user: User,
    candidate: User,
) -> float:
    if not current_user.location or not candidate.location:
        return 0.0

    if current_user.location.lower() == candidate.location.lower():
        return 1.0

    return 0.0
    

def title_similarity(
    current_user: User,
    candidate: User,
) -> float:
    if not current_user.title or not candidate.title:
        return 0.0

    current_title = current_user.title.lower()
    candidate_title = candidate.title.lower()

    if current_title == candidate_title:
        return 1.0

    current_words = set(current_title.split())
    candidate_words = set(candidate_title.split())

    if not current_words or not candidate_words:
        return 0.0

    overlap = current_words & candidate_words

    return len(overlap) / len(current_words | candidate_words)

def experience_similarity(
    current_user: User,
    candidate: User,
) -> float:
    if not current_user.experience or not candidate.experience:
        return 0.0

    current_experience = {
        (
            experience.title.lower(),
            experience.company.lower(),
        )
        for experience in current_user.experience
    }

    candidate_experience = {
        (
            experience.title.lower(),
            experience.company.lower(),
        )
        for experience in candidate.experience
    }

    overlap = current_experience & candidate_experience

    if not overlap:
        return 0.0

    return len(overlap) / len(
        current_experience | candidate_experience
    )

def education_similarity(
    current_user: User,
    candidate: User,
) -> float:
    if not current_user.education or not candidate.education:
        return 0.0

    current_schools = {
        education.school.lower()
        for education in current_user.education
    }

    candidate_schools = {
        education.school.lower()
        for education in candidate.education
    }

    overlap = current_schools & candidate_schools

    if not overlap:
        return 0.0

    return len(overlap) / len(
        current_schools | candidate_schools
    )

