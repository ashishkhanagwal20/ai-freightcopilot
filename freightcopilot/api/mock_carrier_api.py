from fastapi import FastAPI, HTTPException

from freightcopilot.schemas import Carrier

app = FastAPI(title="Mock Carrier Service")


CARRIERS = {
    "CARRIER-014": Carrier(
        carrier_id="CARRIER-014",
        name="Northstar Freight",
        equipment=["dry_van"],
        max_weight_lbs=42000,
        hazmat_enabled=False,
        required_pickup_notice_hours=24,
    )
}


@app.get("/carriers/{carrier_id}", response_model=Carrier)
def get_carrier(carrier_id: str) -> Carrier:
    carrier = CARRIERS.get(carrier_id)

    if carrier is None:
        raise HTTPException(status_code=404, detail="Carrier not found")

    return carrier
