from freightcopilot.documents import load_documents, load_questions


if __name__ == "__main__":
    documents = load_documents()
    questions = load_questions()
    print(f"Loaded {len(documents)} documents and {len(questions)} questions")
    for document in documents:
        print(f"- {document.document_id}: {len(document.content)} characters")
