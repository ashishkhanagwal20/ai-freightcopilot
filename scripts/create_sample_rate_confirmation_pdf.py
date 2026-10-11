from pathlib import Path

import pymupdf

from freightcopilot.config import DATA_DIR


def main() -> None:
    output_path = DATA_DIR / "sample_rate_confirmation.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    document = pymupdf.open()
    page = document.new_page()
    page.insert_textbox(
        pymupdf.Rect(54, 48, 558, 760),
        """NORTHSTAR FREIGHT - RATE CONFIRMATION

Dispatch copy | Fictional training document

LOAD NUMBER: LOAD-1001
Carrier: Northstar Freight (CARRIER-014)
Agreed linehaul: USD 1,850.00

EQUIPMENT / COMMODITY
Equipment: Dry Van
Cargo weight: 38,000 lbs

ROUTE AND APPOINTMENTS
Origin: Chicago, Illinois
Pickup appointment: October 9, 2026 at 9:00 AM Central Time
Destination: Columbus, Ohio
Delivery appointment: October 9, 2026 by 5:00 PM Eastern Time

DOCUMENT REQUIREMENTS
Carrier must provide signed proof of delivery after unloading.
All appointment times are local to the facility.

Dispatch note: confirm appointment with carrier before tender.
This synthetic PDF is for local project evaluation only.""",
        fontsize=11,
        lineheight=1.35,
    )
    document.set_metadata(
        {
            "title": "Fictional Rate Confirmation LOAD-1001",
            "author": "FreightCopilot synthetic data generator",
        }
    )
    document.save(output_path)
    document.close()
    print(f"Created synthetic sample PDF: {output_path}")


if __name__ == "__main__":
    main()
