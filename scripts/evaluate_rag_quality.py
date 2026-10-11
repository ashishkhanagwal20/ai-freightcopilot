import argparse

from google import genai
from ragas import EvaluationDataset, evaluate
from ragas.llms import llm_factory
from ragas.metrics import FactualCorrectness, Faithfulness, LLMContextRecall
from ragas.run_config import RunConfig

from freightcopilot.config import GENERATION_MODEL, get_gemini_api_key
from freightcopilot.database import connect_database
from freightcopilot.documents import load_questions
from freightcopilot.generation import build_rag_prompt, generate_answer
from freightcopilot.retrieval import (
    retrieve_chunks,
    retrieve_hybrid_chunks,
    retrieve_reranked_chunks,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a Gemini-judged RAGAS evaluation."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of questions to score (default: 3).",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Zero-based index of the first question to score (default: 0).",
    )
    parser.add_argument(
        "--retriever",
        choices=("dense", "hybrid", "reranked"),
        default="hybrid",
    )
    parser.add_argument(
        "--show-examples",
        action="store_true",
        help="Print each evaluated question, answer, reference, and context.",
    )
    args = parser.parse_args()

    if args.limit < 1:
        raise ValueError("--limit must be at least 1.")

    all_questions = load_questions()
    if not all_questions:
        raise ValueError("No evaluation questions were loaded.")

    if args.start_index < 0 or args.start_index >= len(all_questions):
        raise ValueError(
            f"--start-index must be between 0 and {len(all_questions) - 1}."
        )

    questions = all_questions[
        args.start_index : args.start_index + args.limit
    ]
    if not questions:
        raise ValueError("No evaluation questions were selected.")

    retrievers = {
        "dense": retrieve_chunks,
        "hybrid": retrieve_hybrid_chunks,
        "reranked": retrieve_reranked_chunks,
    }
    retrieve = retrievers[args.retriever]
    records = []

    with connect_database() as connection:
        for item in questions:
            if args.retriever == "reranked":
                chunks = retrieve(
                    item["question"],
                    connection,
                    top_k=3,
                    candidate_k=5,
                )
            else:
                chunks = retrieve(
                    item["question"],
                    connection,
                    top_k=3,
                )

            answer = generate_answer(
                build_rag_prompt(item["question"], chunks)
            )
            records.append(
                {
                    "user_input": item["question"],
                    "retrieved_contexts": [
                        chunk.content for chunk in chunks
                    ],
                    "response": answer,
                    "reference": item["reference_answer"],
                }
            )

    evaluation_dataset = EvaluationDataset.from_list(records)
    gemini_client = genai.Client(api_key=get_gemini_api_key())
    evaluator_llm = llm_factory(
        GENERATION_MODEL,
        provider="google",
        client=gemini_client,
    )

    result = evaluate(
        dataset=evaluation_dataset,
        metrics=[
            LLMContextRecall(),
            Faithfulness(),
            FactualCorrectness(),
        ],
        llm=evaluator_llm,
        run_config=RunConfig(max_workers=1),
        raise_exceptions=True,
    )

    print(f"Retriever: {args.retriever}")
    print(f"Question start index: {args.start_index}")
    print(f"Questions scored: {len(records)}")
    print(result)
    print(result.to_pandas().to_string(index=False))

    if args.show_examples:
        for index, record in enumerate(records, start=args.start_index + 1):
            print(f"\n--- Evaluation example {index} ---")
            print(f"Question: {record['user_input']}")
            print(f"Reference: {record['reference']}")
            print(f"Answer: {record['response']}")
            print("Retrieved contexts:")
            for context in record["retrieved_contexts"]:
                print(f"\n{context}")

    print(
        "These are model-judged scores on a small synthetic set. "
        "Review answers and contexts before making quality claims."
    )


if __name__ == "__main__":
    main()