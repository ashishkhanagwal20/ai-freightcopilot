import argparse

from freightcopilot.database import connect_database
from freightcopilot.generation import build_rag_prompt, generate_answer
from freightcopilot.retrieval import retrieve_chunks


parser = argparse.ArgumentParser(description="Ask FreightCopilot a RAG question")
parser.add_argument(
    "question", nargs="?", default="When is a driver required to take a break?"
)
args = parser.parse_args()

with connect_database() as connection:
    evidence = retrieve_chunks(args.question, connection)

if not evidence:
    print("I couldn't find supporting information in the documents.")
else:
    prompt = build_rag_prompt(args.question, evidence)
    print(generate_answer(prompt))
