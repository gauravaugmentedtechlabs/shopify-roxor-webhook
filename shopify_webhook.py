# file: shopify_webhook.py

from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib
import base64
import json
import os
import logging
import paramiko
from datetime import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom

app = FastAPI()

SHOPIFY_WEBHOOK_SECRET = "3be9a8d7f2b22fa69a989d3844877d4c5bd4171e71f9a6bc94f75b775233c682"

# =========================================
# BASE FOLDER
# =========================================

BASE_PATH = "/usr/share/nginx/html/shopify-webhook/orders"

os.makedirs(BASE_PATH, exist_ok=True)

# =========================================
# LOGGING
# =========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("shopify_webhook.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# =========================================
# SFTP CONFIG
# =========================================

SFTP_HOST = "ftp.roxorgroup.com"
SFTP_PORT = 22
SFTP_USERNAME = "BSHPSFTP"
SFTP_PASSWORD = "iQnFeVK23k#nKxIT"
SFTP_REMOTE_FOLDER = "/ORDERS"

# =========================================
# SFTP UPLOAD
# =========================================

def upload_to_sftp(local_file):

    if not SFTP_HOST:
        logger.warning("SFTP not configured. Skipping upload.")
        return False

    transport = None
    sftp = None

    try:
        logger.info(f"Connecting to SFTP server: {SFTP_HOST}")

        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(
            username=SFTP_USERNAME,
            password=SFTP_PASSWORD
        )

        sftp = paramiko.SFTPClient.from_transport(transport)

        try:
            sftp.chdir(SFTP_REMOTE_FOLDER)
        except IOError:
            logger.warning(f"Creating remote folder: {SFTP_REMOTE_FOLDER}")
            sftp.mkdir(SFTP_REMOTE_FOLDER)

        remote_file = f"{SFTP_REMOTE_FOLDER}/{os.path.basename(local_file)}"

        sftp.put(local_file, remote_file)

        logger.info(f"SFTP Upload Success: {remote_file}")
        return True

    except Exception as e:
        logger.exception(f"SFTP Upload Failed: {e}")
        return False

    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()


# =========================================
# VERIFY SHOPIFY WEBHOOK
# =========================================

def verify_webhook(data, hmac_header):

    digest = hmac.new(
        SHOPIFY_WEBHOOK_SECRET.encode("utf-8"),
        data,
        hashlib.sha256
    ).digest()

    calculated_hmac = base64.b64encode(digest).decode()

    return hmac.compare_digest(
        calculated_hmac,
        hmac_header
    )

# =========================================
# SAFE VALUE
# =========================================

def safe_value(value, default="."):

    if value is None:
        return default

    value = str(value).strip()

    if value == "":
        return default

    return value

# =========================================
# PRETTY XML
# =========================================

def prettify_xml(element):

    rough_string = ET.tostring(
        element,
        encoding="utf-8"
    )

    reparsed = minidom.parseString(
        rough_string
    )

    return reparsed.toprettyxml(
        indent="\t"
    )

# =========================================
# GENERATE ORDERS02
# =========================================

def generate_orders02(order):

    root = ET.Element("ORDERS02")

    idoc = ET.SubElement(
        root,
        "IDOC",
        BEGIN="1"
    )

    # =========================================
    # EDI HEADER
    # =========================================

    now = datetime.now()

    created_date = now.strftime("%Y%m%d")
    created_time = now.strftime("%H%M%S")
    serial = now.strftime("%Y%m%d%H%M%S")

    edi = ET.SubElement(
        idoc,
        "EDI_DC40",
        SEGMENT="1"
    )

    edi_fields = {
        "TABNAM": "EDI_DC40",
        "MANDT": "400",
        "DOCNUM": "",
        "DOCREL": "",
        "STATUS": "",
        "DIRECT": "2",
        "OUTMOD": "",
        "IDOCTYP": "ORDERS02",
        "MESTYP": "ORDERS",
        "SNDPOR": "ULTRA_XML",
        "SNDPRT": "LS",
        "SNDPRN": "DUMMYEDI",
        "SNDPFC": " ",
        "RCVPOR": "",
        "RCVPRT": "LS",
        "RCVPFC": "",
        "RCVPRN": "DUMMYEDI",
        "CREDAT": created_date,
        "CRETIM": created_time,
        "SERIAL": serial
    }

    for key, value in edi_fields.items():

        ET.SubElement(
            edi,
            key
        ).text = value

    # =========================================
    # HEADER DATA
    # =========================================

    e1edk01 = ET.SubElement(
        idoc,
        "E1EDK01",
        SEGMENT="1"
    )

    ET.SubElement(
        e1edk01,
        "CURCY"
    ).text = safe_value(
        order.get("currency"),
        "GBP"
    )

    ET.SubElement(
        e1edk01,
        "WKURS"
    ).text = "1.00000"

    ET.SubElement(
        e1edk01,
        "VSART"
    ).text = "01"

    # =========================================
    # ORGANIZATION DATA
    # =========================================

    org_segments = [
        ("006", "10"),
        ("007", "10"),
        ("008", "1000"),
        ("012", "ZOR"),
        ("019", "EDI")
    ]

    for qualf, orgid in org_segments:

        seg = ET.SubElement(
            idoc,
            "E1EDK14",
            SEGMENT="1"
        )

        ET.SubElement(
            seg,
            "QUALF"
        ).text = qualf

        ET.SubElement(
            seg,
            "ORGID"
        ).text = orgid

    # =========================================
    # ORDER DATE
    # =========================================

    created_at = safe_value(
        order.get("created_at"),
        ""
    )

    order_date = created_at[:10].replace("-", "")

    e1edk03 = ET.SubElement(
        idoc,
        "E1EDK03",
        SEGMENT="1"
    )

    ET.SubElement(
        e1edk03,
        "IDDAT"
    ).text = "002"

    ET.SubElement(
        e1edk03,
        "DATUM"
    ).text = order_date

    # =========================================
    # AG PARTNER
    # =========================================

    ag = ET.SubElement(
        idoc,
        "E1EDKA1",
        SEGMENT="1"
    )

    ET.SubElement(
        ag,
        "PARVW"
    ).text = "AG"

    ET.SubElement(
        ag,
        "PARTN"
    ).text = "TES001"

    ET.SubElement(
        ag,
        "IHREZ"
    ).text = ""

    # =========================================
    # WE PARTNER
    # =========================================

    shipping = order.get(
        "shipping_address",
        {}
    )

    we = ET.SubElement(
        idoc,
        "E1EDKA1",
        SEGMENT="1"
    )

    ET.SubElement(
        we,
        "PARVW"
    ).text = "WE"

    ET.SubElement(
        we,
        "PARNR"
    ).text = "TES001"

    company_name = shipping.get("company")

    if not company_name:

        company_name = (
            safe_value(
                shipping.get("first_name"),
                ""
            )
            + " "
            + safe_value(
                shipping.get("last_name"),
                ""
            )
        ).strip()

    ET.SubElement(
        we,
        "NAME1"
    ).text = safe_value(company_name)

    ET.SubElement(
        we,
        "NAME2"
    ).text = "."

    ET.SubElement(
        we,
        "NAME3"
    ).text = " "

    ET.SubElement(
        we,
        "STRAS"
    ).text = safe_value(
        shipping.get("address1")
    )

    ET.SubElement(
        we,
        "STRS2"
    ).text = safe_value(
        shipping.get("address2")
    )

    ET.SubElement(
        we,
        "ORT01"
    ).text = safe_value(
        shipping.get("city")
    )

    ET.SubElement(
        we,
        "ORT02"
    ).text = "."

    ET.SubElement(
        we,
        "PSTLZ"
    ).text = safe_value(
        shipping.get("zip")
    )

    ET.SubElement(
        we,
        "LAND1"
    ).text = safe_value(
        shipping.get("country_code"),
        "GB"
    )

    ET.SubElement(
        we,
        "TELF1"
    ).text = safe_value(
        shipping.get("phone"),
        "0"
    )

    ET.SubElement(
        we,
        "TELF2"
    ).text = "0"

    ET.SubElement(
        we,
        "TELFX"
    ).text = "0"

    ET.SubElement(
        we,
        "ILNNR"
    ).text = " "

    # =========================================
    # PURCHASE ORDER
    # =========================================

    po_number = safe_value(
        order.get("name"),
        "PO00001"
    ).replace("#", "")

    po1 = ET.SubElement(
        idoc,
        "E1EDK02",
        SEGMENT="1"
    )

    ET.SubElement(
        po1,
        "QUALF"
    ).text = "001"

    ET.SubElement(
        po1,
        "BELNR"
    ).text = po_number

    po2 = ET.SubElement(
        idoc,
        "E1EDK02",
        SEGMENT="1"
    )

    ET.SubElement(
        po2,
        "QUALF"
    ).text = "044"

    ET.SubElement(
        po2,
        "BELNR"
    ).text = ""

    # =========================================
    # TEXT SEGMENT Z002
    # =========================================

    text1 = ET.SubElement(
        idoc,
        "E1EDKT1",
        SEGMENT="1"
    )

    ET.SubElement(
        text1,
        "TDID"
    ).text = "Z002"

    text1_child = ET.SubElement(
        text1,
        "E1EDKT2",
        SEGMENT="1"
    )

    ET.SubElement(
        text1_child,
        "TDLINE"
    ).text = " "

    # =========================================
    # TEXT SEGMENT 0012
    # =========================================

    text2 = ET.SubElement(
        idoc,
        "E1EDKT1",
        SEGMENT="1"
    )

    ET.SubElement(
        text2,
        "TDID"
    ).text = "0012"

    text2_child = ET.SubElement(
        text2,
        "E1EDKT2",
        SEGMENT="1"
    )

    ET.SubElement(
        text2_child,
        "TDLINE"
    ).text = po_number

    # =========================================
    # LINE ITEMS
    # =========================================

    for item in order.get("line_items", []):

        product_seg = ET.SubElement(
            idoc,
            "E1EDP01",
            SEGMENT="1"
        )

        ET.SubElement(
            product_seg,
            "MENGE"
        ).text = str(
            item.get("quantity", 1)
        )

        ET.SubElement(
            product_seg,
            "PEINH"
        ).text = "1"

        sku = safe_value(
            item.get("sku")
        )

        # QUALF 001

        p19_1 = ET.SubElement(
            product_seg,
            "E1EDP19",
            SEGMENT="1"
        )

        ET.SubElement(
            p19_1,
            "QUALF"
        ).text = "001"

        ET.SubElement(
            p19_1,
            "IDTNR"
        ).text = sku

        # QUALF 002

        p19_2 = ET.SubElement(
            product_seg,
            "E1EDP19",
            SEGMENT="1"
        )

        ET.SubElement(
            p19_2,
            "QUALF"
        ).text = "002"

        ET.SubElement(
            p19_2,
            "IDTNR"
        ).text = sku

        # TEXT SEGMENT

        pt1 = ET.SubElement(
            product_seg,
            "E1EDPT1",
            SEGMENT="1"
        )

        pt2 = ET.SubElement(
            pt1,
            "E1EDPT2",
            SEGMENT="1"
        )

        ET.SubElement(
            pt2,
            "TDLINE"
        ).text = ""

    # =========================================
    # SUMMARY
    # =========================================

    summary = ET.SubElement(
        idoc,
        "E1EDS01",
        SEGMENT="1"
    )

    ET.SubElement(
        summary,
        "SUMID"
    ).text = "001"

    ET.SubElement(
        summary,
        "SUMME"
    ).text = ""

    return prettify_xml(root)

# =========================================
# ROOT
# =========================================

@app.get("/")
async def root():

    return {
        "message": "Shopify Webhook Running"
    }

# =========================================
# SHOPIFY WEBHOOK
# =========================================

@app.post("/webhook/orders")
async def order_webhook(
    request: Request,
    x_shopify_topic: str = Header(None),
    x_shopify_hmac_sha256: str = Header(None)
):

    raw_body = await request.body()

    # =========================================
    # VERIFY WEBHOOK
    # =========================================

    if not verify_webhook(
        raw_body,
        x_shopify_hmac_sha256
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid HMAC"
        )

    # =========================================
    # LOAD ORDER JSON
    # =========================================

    order = json.loads(raw_body)

    order_id = order.get("id")

    order_name = order.get(
        "name",
        "UNKNOWN"
    )

    clean_order_name = order_name.replace(
        "#",
        ""
    )

    print("\n===================================")
    print(f"SHOPIFY EVENT: {x_shopify_topic}")
    print(f"ORDER ID: {order_id}")
    print(f"ORDER NAME: {order_name}")
    print("===================================\n")

    # =========================================
    # CREATE ORDER FOLDER
    # =========================================

    order_folder = (
        f"{BASE_PATH}/{clean_order_name}"
    )

    os.makedirs(
        order_folder,
        exist_ok=True
    )

    # =========================================
    # SAVE SHOPIFY JSON
    # =========================================

    json_file = (
        f"{order_folder}/shopify_order.json"
    )

    with open(
        json_file,
        "w"
    ) as f:

        json.dump(
            order,
            f,
            indent=4
        )

    # =========================================
    # GENERATE XML
    # =========================================

    orders02_xml = generate_orders02(order)

    # =========================================
    # SAVE XML
    # =========================================

    orders02_path = (
        f"{order_folder}/{order_id}.xml"
    )

    with open(
        orders02_path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(orders02_xml)

    logger.info(
        f"UPDATED XML: {orders02_path}"
    )

    upload_to_sftp(
        orders02_path
    )

    # =========================================
    # RESPONSE
    # =========================================

    return {
        "success": True,
        "shopify_topic": x_shopify_topic,
        "order_id": order_id,
        "order_folder": order_folder,
        "updated_file": orders02_path
   }
