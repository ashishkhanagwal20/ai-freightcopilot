from freightcopilot.embeddings import get_embedding_model


embedding = get_embedding_model().encode(
    "Drivers need a break after eight hours of driving."
)
print(f"Vector dimensions: {embedding.shape[0]}")
print(f"First five values: {embedding[:5]}")
