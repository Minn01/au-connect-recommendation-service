import os

def required(name: str) -> str:
    val = os.getenv(name)

    if not val:
        raise RuntimeError(f"Environment variable {name} is missing")

    return val

# all environment variables here--  
 
MONGODB_URI = required("MONGODB_URI")
MONGODB_DB = required("MONGODB_DB")
INTERNAL_API_KEY = required("INTERNAL_API_KEY")
