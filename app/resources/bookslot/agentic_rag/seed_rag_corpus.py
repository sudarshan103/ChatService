import argparse
import os

import psycopg2
from openai import OpenAI

from config import Config


def _build_docs() -> list[dict]:
    return [
        {
            "record_type": "specialty_summary",
            "specialty": "Orthopedic",
            "provider_id": None,
            "doctor_name": None,
            "specialty_tags": ["orthopedic", "knee_pain", "joint_pain"],
            "content": "Orthopedic treats bones, joints, muscles, ligaments, and common knee pain concerns.",
        },
        {
            "record_type": "doctor_profile",
            "specialty": "Orthopedic",
            "provider_id": 3,
            "doctor_name": "Dr. Nikhil Jadhav",
            "specialty_tags": ["orthopedic", "knee_pain", "sports_injury"],
            "content": "Dr. Nikhil Jadhav is an Orthopedic specialist available for bone, joint, and ligament issues.",
        },
        {
            "record_type": "specialty_summary",
            "specialty": "Cardiologist",
            "provider_id": None,
            "doctor_name": None,
            "specialty_tags": ["cardiology", "chest_pain", "palpitations"],
            "content": "Cardiology focuses on heart health, including chest discomfort, palpitations, and rhythm issues.",
        },
        {
            "record_type": "doctor_profile",
            "specialty": "Cardiologist",
            "provider_id": 1,
            "doctor_name": "Dr. Priya",
            "specialty_tags": ["cardiology", "heart_consult", "blood_pressure"],
            "content": "Dr. Priya is a Cardiologist providing consultations for heart and blood pressure related conditions.",
        },
        {
            "record_type": "specialty_summary",
            "specialty": "Gastroenterology",
            "provider_id": None,
            "doctor_name": None,
            "specialty_tags": ["gastroenterology", "acidity", "abdominal_pain"],
            "content": "Gastroenterology handles digestive tract conditions such as acidity, indigestion, and abdominal discomfort.",
        },
        {
            "record_type": "doctor_profile",
            "specialty": "Gastroenterology",
            "provider_id": 2,
            "doctor_name": "Dr. Sheetal",
            "specialty_tags": ["gastroenterology", "acidity", "digestive_health"],
            "content": "Dr. Sheetal is a Gastroenterology specialist for digestive complaints and abdominal discomfort.",
        },
    ]


def seed_medical_corpus(clear_seed_rows: bool = False) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")

    conn = psycopg2.connect(
        host=Config.POSTGRES_HOST,
        port=Config.POSTGRES_PORT,
        dbname=Config.POSTGRES_DB,
        user=Config.POSTGRES_USERNAME,
        password=Config.POSTGRES_PASSWORD,
    )
    conn.autocommit = True
    cur = conn.cursor()

    table_name = Config.PGVECTOR_TABLE
    embedding_model = Config.RAG_EMBEDDING_MODEL
    docs = _build_docs()

    if clear_seed_rows:
        cur.execute(
            f"DELETE FROM {table_name} WHERE record_type IN ('specialty_summary', 'doctor_profile')"
        )

    client = OpenAI(api_key=api_key)

    insert_sql = f"""
    INSERT INTO {table_name}
    (record_type, specialty, provider_id, doctor_name, specialty_tags, content, embedding)
    VALUES (%s, %s, %s, %s, %s::text[], %s, %s::vector)
    """

    for doc in docs:
        embedding = client.embeddings.create(
            model=embedding_model,
            input=doc["content"],
        ).data[0].embedding
        vector_literal = "[" + ",".join(str(value) for value in embedding) + "]"
        cur.execute(
            insert_sql,
            (
                doc["record_type"],
                doc["specialty"],
                doc["provider_id"],
                doc["doctor_name"],
                doc["specialty_tags"],
                doc["content"],
                vector_literal,
            ),
        )

    cur.close()
    conn.close()

    print(f"Seed completed: inserted {len(docs)} rows into {table_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed medical_corpus_vectors for agentic RAG")
    parser.add_argument(
        "--clear-seed-rows",
        action="store_true",
        help="Delete existing specialty_summary and doctor_profile rows before inserting",
    )
    args = parser.parse_args()
    seed_medical_corpus(clear_seed_rows=args.clear_seed_rows)


if __name__ == "__main__":
    main()
