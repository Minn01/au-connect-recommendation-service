from dataclasses import dataclass

from au_connect_recommendation_service.enums.account_status import AccountStatus
from au_connect_recommendation_service.models.education import Education
from au_connect_recommendation_service.models.experience import Experience

@dataclass
class User:
    id: str
    # general information
    username: str
    title: str | None
    location: str | None
    about: str | None
    
    # account availability
    account_status: AccountStatus 
    
    # work in progress
    experience: list[Experience]
    education: list[Education]

def map_user(doc: dict) -> User:
    return User(
        id=str(doc["_id"]),
        username=doc["username"],
        title=doc.get("title"),
        location=doc.get("location"),
        about=doc.get("about"),
        account_status=AccountStatus(doc["accountStatus"]),
        experience=[],
        education=[],
    )