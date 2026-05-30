#!/usr/bin/env python3
"""Bulk-import products + initial stock into Odoo via XML-RPC."""
import json
import os
import sys
import urllib.request
from pathlib import Path

# Load .env
env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

URL = f"https://{os.environ['SUBDOMAIN']}"
DB = os.environ["ODOO_DB_NAME"]
USER = os.environ["ODOO_ADMIN_USER"]
API_KEY = os.environ["ODOO_API_KEY"]

# Category IDs (already created)
CAT_STAND = 4
CAT_COOLERS = 5
CAT_COOLER = 8
CAT_NECK_COOLER = 9
CAT_COOLING_CHAMBER = 10
CAT_BATTERY = 11
CAT_CHARGING_DOCK = 12
CAT_GAME_CTRL = 13
CAT_ARM_STANDS = 6
CAT_MICS = 7

STOCK_LOC_ID = 8  # WH/Stock

# (name, qty, categ_id)
PRODUCTS = [
    # Stand and Others
    ("Gorilla", 0, CAT_STAND),
    ("Pop Filter Alogy", 250, CAT_STAND),
    ("Pop Filter", 0, CAT_STAND),
    ("Pop Filter Afys", 0, CAT_STAND),
    ("U Shaped Filter", 0, CAT_STAND),
    ("Ball Head", 0, CAT_STAND),
    ("HH 2 in 1", 0, CAT_STAND),
    ("Ipad Holder 1/4", 27, CAT_STAND),
    ("Shock Mount", 0, CAT_STAND),
    ("Shock Mount + Small Filter", 0, CAT_STAND),
    ("Shock Mount + Small Filter with Tripod", 0, CAT_STAND),
    ("Round Plastic Base Mobile Stand", 0, CAT_STAND),
    ("Mic Tripod", 0, CAT_STAND),
    ("BM800 Holder 16-27", 0, CAT_STAND),
    ("Metal Round Base 3 in 1", 0, CAT_STAND),
    ("DP Stand Metal (S-L) Grey", 146, CAT_STAND),
    ("C06 Magsafe Stand", 187, CAT_STAND),
    ("Vaccum A2 Stand White", 62, CAT_STAND),
    ("Vaccum A2 Stand Black", 4, CAT_STAND),
    ("Vaccum T30 Stand", 15, CAT_STAND),
    ("Travel Stand", 156, CAT_STAND),
    ("3 in 1 Mic Stand (Bukhari)", 25, CAT_STAND),
    ("Mobile Stand (750)", 0, CAT_STAND),
    ("Q10 JoyStick Red", 0, CAT_STAND),
    ("Q10 JoyStick Yellow", 0, CAT_STAND),
    ("Q10 JoyStick Blue", 0, CAT_STAND),
    ("Clamp Simple", 0, CAT_STAND),
    ("Clamp Extended", 82, CAT_STAND),
    ("Clamp Long (PSA)", 117, CAT_STAND),
    ("Clamp Regular (Aluminium)", 118, CAT_STAND),
    ("XLR Cable Black ST", 399, CAT_STAND),
    ("XLR Cable 3.5MM - H - 5M", 30, CAT_STAND),
    ("XLR Cable TYPE-C - 5M", 98, CAT_STAND),
    ("XLR Cable MF - 5M", 43, CAT_STAND),
    ("XLR Cable MF - 2M", 60, CAT_STAND),
    ("XLR Cable BLACK-H - 2M", 134, CAT_STAND),
    ("XLR Cable Red", 330, CAT_STAND),
    ("3 in 1 Mobile Holder Plastic", 0, CAT_STAND),
    ("3 in 1 Mobile Holder Metal", 0, CAT_STAND),
    ("Metal Tripod 1/4 Big 19CM", 0, CAT_STAND),
    ("Metal Tripod 1/4 Small 14CM", 0, CAT_STAND),
    ("Dynamic U Metal Clip (RGB MIC)", 0, CAT_STAND),
    ("USB Light", 0, CAT_STAND),
    ("Joystick", 0, CAT_STAND),
    ("U HOLDER", 0, CAT_STAND),
    ("U HOLDER NEW", 0, CAT_STAND),
    ("U HOLDER +60-100", 0, CAT_STAND),
    ("U HOLDER +55-85", 0, CAT_STAND),
    ("180 BALL HEAD HOLDER", 0, CAT_STAND),
    ("180 BALL HEAD HOLDER NEW", 0, CAT_STAND),
    ("ST TABLET HOLDER", 0, CAT_STAND),
    ("ST U HOLDER", 0, CAT_STAND),
    ("DYNAMIC MIC HOLDER", 0, CAT_STAND),
    ("1/4 TO BALLHEAD CONVERTOR", 0, CAT_STAND),
    ("PASTIC BALLHEAD", 0, CAT_STAND),
    ("U HOLDER + 55-850GOPRO", 0, CAT_STAND),
    ("U HOLDER 55-850GOPRO", 0, CAT_STAND),
    ("CONDENCER MIC HOLDER", 0, CAT_STAND),
    ("BUTTERFULY MIC HOLDER", 0, CAT_STAND),
    ("BUTTERFULY TABLET HOLDER", 0, CAT_STAND),
    ("BIG BALL HEAD", 25, CAT_STAND),
    ("BIG PALSTIC CLAMP", 0, CAT_STAND),
    ("26 CM Ring Light", 3, CAT_STAND),
    ("Desktop Stand ST", 8, CAT_STAND),
    # Coolers (image 2 col 1)
    ("DLA6", 0, CAT_COOLER),
    ("DLA8", 50, CAT_COOLER),
    ("DL05 Tablet", 0, CAT_COOLER),
    ("DL05", 74, CAT_COOLER),
    ("DL06", 0, CAT_COOLER),
    ("DL10", 0, CAT_COOLER),
    ("DL16", 0, CAT_COOLER),
    ("DL20", 0, CAT_COOLER),
    ("CX01", 0, CAT_COOLER),
    ("CX04", 3, CAT_COOLER),
    ("CX05 Tablet", 0, CAT_COOLER),
    ("CX06", 2, CAT_COOLER),
    ("CX07", 1, CAT_COOLER),
    ("CX08 Frozen Model", 0, CAT_COOLER),
    ("CX08 Pro", 0, CAT_COOLER),
    ("CX08 AI", 0, CAT_COOLER),
    ("CX09", 0, CAT_COOLER),
    ("CX10 Pro", 0, CAT_COOLER),
    ("CX10 Digital Display", 0, CAT_COOLER),
    ("CX10 Basic Model", 1, CAT_COOLER),
    ("CX12", 20, CAT_COOLER),
    ("CX15 5V", 0, CAT_COOLER),
    ("DG01", 26, CAT_NECK_COOLER),
    ("VC01", 0, CAT_COOLING_CHAMBER),
    ("Battery", 76, CAT_BATTERY),
    ("DL10 Battery", 0, CAT_CHARGING_DOCK),
    ("AK03", 22, CAT_GAME_CTRL),
    ("Cx20 Black", 20, CAT_COOLER),
    ("Cx20 White", 44, CAT_COOLER),
    ("Cx21 White", -17, CAT_COOLER),
    ("Magnetic Plate", 38, CAT_COOLING_CHAMBER),
    ("Clips", 4, CAT_COOLING_CHAMBER),
    # Arm Stands (image 2 col 2)
    ("ArmStand 1/4 35 x 35", 0, CAT_ARM_STANDS),
    ("ArmStand 1/4 25 x 25 No Holder", 0, CAT_ARM_STANDS),
    ("Arm Mic Stand 35 X 35", 0, CAT_ARM_STANDS),
    ("Arm Mic Stand Plus (Maono Style)", 28, CAT_ARM_STANDS),
    ("Extended Tablet", 29, CAT_ARM_STANDS),
    ("Extended Mobile", 0, CAT_ARM_STANDS),
    ("Arm Stand With Shock Mount And Filter", 0, CAT_ARM_STANDS),
    ("Arm Stand, Shock Mount, Pop Filter (MIC KIT)", 48, CAT_ARM_STANDS),
    ("Arm Stand Magnetic", 137, CAT_ARM_STANDS),
    ("Arm Stand Lifting Rod", 0, CAT_ARM_STANDS),
    ("Metal Base + ArmStand (25x25) Tablet Heavy Plate", 34, CAT_ARM_STANDS),
    ("Metal Base + ArmStand (25x25) Tablet Light Plate", 0, CAT_ARM_STANDS),
    ("Metal base ArmStand (25 x 25) 3 Shaft Tablet Holder", 0, CAT_ARM_STANDS),
    ("Metal base ArmStand (25 x 25) 2 Shaft Tablet Holder", 0, CAT_ARM_STANDS),
    ("Sofa Stand Tablet (Light)", 31, CAT_ARM_STANDS),
    ("New MHS 180 with Clips", 291, CAT_ARM_STANDS),
    ("Arm Stand Ball Head Big Plastic Base Mobile", 0, CAT_ARM_STANDS),
    ("Arm Stand Ball Head Big Plastic Base Tablet", 0, CAT_ARM_STANDS),
    ("Arm Stand PSA", 38, CAT_ARM_STANDS),
    ("GAZ 90", 7, CAT_ARM_STANDS),
    ("GAZ 80 A", 3, CAT_ARM_STANDS),
    ("GAZ 80 B", 2, CAT_ARM_STANDS),
    ("Arm Stand 25 x 25 180 Round Base", 0, CAT_ARM_STANDS),
    ("GAZ NB10 (ROD)", 7, CAT_ARM_STANDS),
    ("ARM STAND 180 35 X 35", 9, CAT_ARM_STANDS),
    ("ARM STAND MHS 35 X 35", 0, CAT_ARM_STANDS),
    ("ARM STAND MIC 35 X 35 WITH CLAMPS & SHOCK MOUNT", 0, CAT_ARM_STANDS),
    ("ARM STAND 180 25 X 25 WITH CLAMPS & SHOCK MOUNT", 0, CAT_ARM_STANDS),
    ("ARM STAND 180 25 X 25 WITH ONLY CLAMPS", 120, CAT_ARM_STANDS),
    ("Sofa Stand Tablet (Heavy)", 0, CAT_ARM_STANDS),
    ("ARM STAND 180 25 X 25", 5, CAT_ARM_STANDS),
    ("only Shock Mount, Pop Filter (MIC KIT)", 36, CAT_ARM_STANDS),
    ("Arm Stand Plastic -1", 75, CAT_ARM_STANDS),
    ("Arm Stand Plastic -2", 75, CAT_ARM_STANDS),
    # Mics and Sound Cards (image 2 col 3)
    ("BM800 Black", 87, CAT_MICS),
    ("BM800 Golden", 41, CAT_MICS),
    ("BM800 Kit WITH U SHAPE POP FILTER", 0, CAT_MICS),
    ("BM800 Set Black", 0, CAT_MICS),
    ("BM800 MIC Set (No Cable) Black", 0, CAT_MICS),
    ("BM800 Glass Only", 0, CAT_MICS),
    ("BM800 Kit Alogy Gold + V8", 0, CAT_MICS),
    ("BM800 Set Gold", 0, CAT_MICS),
    ("BM800 MIC + Ball Foam Only Gold", 0, CAT_MICS),
    ("U87 Mic + Shock Mount Only", 67, CAT_MICS),
    ("AM808 Kit", 0, CAT_MICS),
    ("AM808 Set", 0, CAT_MICS),
    ("Q6S", 28, CAT_MICS),
    ("F998 MAX", 23, CAT_MICS),
    ("V8S English", 24, CAT_MICS),
    ("M8 Black", 11, CAT_MICS),
    ("M8 White", 11, CAT_MICS),
    ("K700", 15, CAT_MICS),
    ("V8 Sound Card", 0, CAT_MICS),
    ("X50", 50, CAT_MICS),
    ("X60", 22, CAT_MICS),
    ("X60 Phantom", 38, CAT_MICS),
]


def jsonrpc(endpoint, method, params):
    req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    data = json.dumps(req).encode("utf-8")
    r = urllib.request.Request(f"{URL}{endpoint}", data=data,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(json.dumps(out["error"], indent=2))
    return out.get("result")


def main():
    print(f"Connecting to {URL} as {USER} ...")
    uid = jsonrpc("/jsonrpc", "call", {
        "service": "common", "method": "authenticate",
        "args": [DB, USER, API_KEY, {}],
    })
    if not uid:
        print("Auth failed.", file=sys.stderr)
        sys.exit(1)
    print(f"Authenticated uid={uid}")

    def call(model, method, args, kwargs=None):
        return jsonrpc("/jsonrpc", "call", {
            "service": "object", "method": "execute_kw",
            "args": [DB, uid, API_KEY, model, method, args, kwargs or {}],
        })

    print(f"Importing {len(PRODUCTS)} products ...")
    created = 0
    skipped = 0
    stock_set = 0

    for name, qty, categ_id in PRODUCTS:
        existing = call("product.template", "search", [[["name", "=", name]]], {"limit": 1})
        if existing:
            print(f"  SKIP (exists): {name}")
            skipped += 1
            tmpl_id = existing[0]
        else:
            tmpl_id = call("product.template", "create", [{
                "name": name,
                "type": "consu",
                "is_storable": True,
                "categ_id": categ_id,
            }])
            created += 1
            print(f"  + {name} (id={tmpl_id})")

        if qty != 0:
            # product.product id from template
            variants = call("product.product", "search",
                            [[["product_tmpl_id", "=", tmpl_id]]], {"limit": 1})
            if not variants:
                print(f"    ! no variant for {name}, skip stock")
                continue
            prod_id = variants[0]
            # Find or create stock.quant in WH/Stock
            quant_ids = call("stock.quant", "search",
                             [[["product_id", "=", prod_id],
                               ["location_id", "=", STOCK_LOC_ID]]],
                             {"limit": 1})
            if quant_ids:
                call("stock.quant", "write", [quant_ids, {"inventory_quantity": qty}])
                quant_id = quant_ids[0]
            else:
                quant_id = call("stock.quant", "create", [{
                    "product_id": prod_id,
                    "location_id": STOCK_LOC_ID,
                    "inventory_quantity": qty,
                }])
            # Apply inventory adjustment
            call("stock.quant", "action_apply_inventory", [[quant_id]])
            stock_set += 1
            print(f"    stock={qty}")

    print(f"\nDone. created={created} skipped={skipped} stock_set={stock_set}")


if __name__ == "__main__":
    main()
