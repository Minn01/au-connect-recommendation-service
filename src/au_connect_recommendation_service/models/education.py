from dataclasses import dataclass


@dataclass
class Education:
    id: str
    school: str
    degree: str
    field_of_study: str
    start_month: int
    start_year: int
    end_month: int
    end_year: int
    user_id: str


def map_education(doc: dict) -> Education:
    return Education(
        id=str(doc["_id"]),
        school=doc["school"],
        degree=doc["degree"],
        field_of_study=doc["fieldOfStudy"],
        start_month=doc["startMonth"],
        start_year=doc["startYear"],
        end_month=doc["endMonth"],
        end_year=doc["endYear"],
        user_id=doc["userId"],
    )
