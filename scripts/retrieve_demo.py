import argparse

from freightcopilot.database import connect_database
from freightcopilot.retrieval import retrieve_chunks


parser = argparse.ArgumentParser(description="Retrieve evidence from pgvector")
parser.add_argument(
    "question", nargs="?", default="When is a driver required to take a break?"
)
parser.add_argument("--top-k", type=int, default=2)
args = parser.parse_args()

with connect_database() as connection:
    chunks = retrieve_chunks(args.question, connection, top_k=args.top_k)

for chunk in chunks:
    print(f"\nSource: {chunk.source_id} ({chunk.document_id})")
    print(f"Similarity: {chunk.similarity:.4f}")
    print(chunk.content[:300])
