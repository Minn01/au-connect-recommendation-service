from dataclasses import dataclass


@dataclass
class Experience:
    id: str
    title: str
    employment_type: str
    company: str
    start_month: int
    start_year: int
    end_month: int | None
    end_year: int | None
    is_current: bool
    user_id: str


def map_experience(doc: dict) -> Experience:
    return Experience(
        id=str(doc["_id"]),
        title=doc["title"],
        employment_type=doc["employmentType"],
        company=doc["company"],
        start_month=doc["startMonth"],
        start_year=doc["startYear"],
        end_month=doc["endMonth"],
        end_year=doc["endYear"],
        is_current=doc["isCurrent"],
        user_id=doc["userId"],
    )
