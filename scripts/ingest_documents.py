from freightcopilot.database import connect_database
from freightcopilot.documents import load_documents
from freightcopilot.embeddings import get_embedding_model


def main() -> None:
    model = get_embedding_model()
    documents = load_documents()

    with connect_database() as connection:
        for document in documents:
            embedding = model.encode(document.content)
            connection.execute(
                """
                INSERT INTO document_chunks
                    (source_id, document_id, chunk_index, content, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (document_id, chunk_index)
                DO UPDATE SET
                    source_id = EXCLUDED.source_id,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding
                """,
                (document.source_id, document.document_id, 0,
                 document.content, embedding),
            )
            print(f"Ingested {document.document_id} [{document.source_id}]")


if __name__ == "__main__":
    main()
