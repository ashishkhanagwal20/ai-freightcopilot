import argparse
import json

from freightcopilot.extraction import extract_load_fields


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured load fields from a selectable-text PDF."
    )
    parser.add_argument("pdf_path", help="Path to the PDF to extract.")
    args = parser.parse_args()

    extracted = extract_load_fields(args.pdf_path)
    print(json.dumps(extracted.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
