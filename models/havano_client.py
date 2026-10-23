# -*- coding: utf-8 -*-
"""
models/havano_client.py
Authoritative standalone client for Havano ZIMRA Cloud Fiscalization API.
Extracted and adapted directly from havanoposdesk_odoo (core/models/fiscal_service.py).
Maintains complete modularity so modifications to Havano do not affect Axis, and vice versa.
"""

import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

_logger = logging.getLogger(__name__)

HS_CODE_DEFAULT = "99999999"


class HavanoClientException(Exception):
    """Custom exception for Havano ZIMRA Cloud API errors."""
    pass


class HavanoZimraCloudClient:
    """
    HTTP Client for Havano ZIMRA Cloud Fiscalization API.
    Identical protocol to havanoposdesk_odoo / HavanoZimraCloudService:
    - 2-tier authentication (CSRF Token + API Key/Secret Token header)
    - Inclusive VAT XML item payload with exact ZIMRA VATR proportion
    - Device ping via /api/method/havanozimracloud.api.pingzimra
    - Invoice & Credit Note submission via /api/method/havanozimracloud.api.sendinvoice
    - SHA-256 Offline Fallback mode
    """

    def __init__(self, base_url: str, api_key: str, api_secret: str, device_sn: str, timeout: int = 10):
        self.base_url = (base_url or 'https://erpfiscal.havano.online').rstrip('/')
        self.api_key = (api_key or '').strip()
        self.api_secret = (api_secret or '').strip()
        self.device_sn = (device_sn or '').strip()
        self.timeout = timeout

    def fetch_csrf_token(self, session: requests.Session) -> tuple:
        """
        Fetch CSRF token from Havano Cloud Frappe API.
        POST /api/method/havanozimracloud.api.token
        """
        token_url = f"{self.base_url}/api/method/havanozimracloud.api.token"
        try:
            _logger.info("[ZIMRA HAVANO] Fetching CSRF Token from %s", token_url)
            resp = session.post(token_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Token request failed HTTP {resp.status_code}: {resp.text[:200]}"
            res_json = resp.json()
            csrf_token = res_json.get("message") or res_json.get("token") or res_json.get("csrf_token")
            if not csrf_token:
                return False, f"Invalid token format in response: {resp.text[:200]}"
            return True, str(csrf_token)
        except Exception as e:
            return False, f"CSRF token connection error: {e}"

    def ping_device(self) -> dict:
        """
        Ping device via Havano Cloud.
        POST /api/method/havanozimracloud.api.pingzimra
        """
        if not self.base_url:
            raise HavanoClientException("Base URL is required")
        if not self.api_key or not self.api_secret:
            raise HavanoClientException("API Key and API Secret are required")
        if not self.device_sn:
            raise HavanoClientException("Device Serial Number (EFD SN) is required")

        session = requests.Session()
        ok, token_or_err = self.fetch_csrf_token(session)
        if not ok:
            raise HavanoClientException(token_or_err)

        csrf_token = token_or_err
        ping_url = f"{self.base_url}/api/method/havanozimracloud.api.pingzimra"
        headers = {
            "X-Frappe-CSRF-Token": csrf_token,
            "Authorization": f"token {self.api_key}:{self.api_secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {"device_sn": str(self.device_sn)}

        try:
            _logger.info("[ZIMRA HAVANO] Pinging device %s at %s", self.device_sn, ping_url)
            resp = session.post(ping_url, data=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                raise HavanoClientException("ZIMRA Authentication Error: Invalid or missing API Key / Secret")
            if resp.status_code != 200:
                raise HavanoClientException(f"HTTP {resp.status_code}: {resp.text[:200]}")

            res_json = resp.json()
            msg = res_json.get("message", {})
            return {
                'success': True,
                'device_sn': self.device_sn,
                'data': msg if isinstance(msg, dict) else res_json,
                'raw': res_json,
            }
        except requests.exceptions.RequestException as e:
            raise HavanoClientException(f"Connection error: {e}")

    def build_items_xml(self, invoice_lines, is_vat_registered: bool = False) -> str:
        """
        Build items XML matching Havano ZIMRA Cloud schema and formulas from havanoposdesk_odoo.
        """
        root = ET.Element("ITEMS")
        idx = 1
        for line in invoice_lines:
            if line.display_type not in (False, 'product'):
                continue
            if line.quantity == 0 and line.price_unit == 0:
                continue

            item_elem = ET.SubElement(root, "ITEM")
            qty = abs(float(line.quantity or 1.0))
            price = abs(float(line.price_unit or 0.0))
            total = abs(float(line.price_total or (qty * price)))

            # Tax rate calculation
            taxes = line.tax_ids.flatten_taxes_hierarchy() if hasattr(line.tax_ids, 'flatten_taxes_hierarchy') else line.tax_ids
            raw_rate = sum(t.amount for t in taxes if t.amount_type == 'percent') if taxes else (15.0 if is_vat_registered else 0.0)

            if not is_vat_registered or raw_rate <= 0.005:
                vat_name = "EXEMPT"
                vat_amount = 0.0
                vatr_val = "0.00"
            else:
                vat_name = "VAT"
                tax_rate = raw_rate if raw_rate > 0 else 15.0
                # Inclusive VAT calculation formula from havanoposdesk_odoo
                vat_amount = round(total - (total / (1.0 + (tax_rate / 100.0))), 2)
                # Format VATR as decimal proportion (e.g. 0.155 for 15.5% or 0.15 for 15%)
                vatr_decimal = tax_rate / 100.0
                vatr_val = f"{vatr_decimal:.3f}".rstrip('0').rstrip('.')

            product = line.product_id
            item_name = str((line.name or (product and product.name) or 'Standard Item')).split('\n')[0][:100]

            code_val = (product and (getattr(product, 'hs_code', None) or getattr(product, 'default_code', None) or getattr(product, 'barcode', None))) or ""
            raw_code = ''.join(c for c in str(code_val) if c.isdigit())
            if len(raw_code) == 8:
                item_code = raw_code
            else:
                item_code = HS_CODE_DEFAULT

            ET.SubElement(item_elem, "HH").text = str(idx)
            ET.SubElement(item_elem, "ITEMCODE").text = item_code
            ET.SubElement(item_elem, "ITEMNAME").text = item_name
            ET.SubElement(item_elem, "ITEMNAME2").text = item_name
            ET.SubElement(item_elem, "QTY").text = f"{qty:.2f}"
            ET.SubElement(item_elem, "PRICE").text = f"{price:.2f}"
            ET.SubElement(item_elem, "TOTAL").text = f"{total:.2f}"
            ET.SubElement(item_elem, "VAT").text = f"{vat_amount:.2f}"
            ET.SubElement(item_elem, "VATR").text = vatr_val
            ET.SubElement(item_elem, "VNAME").text = vat_name[:20]
            idx += 1

        return ET.tostring(root, encoding="unicode")

    def submit_invoice(self, move, is_vat_registered: bool = True) -> dict:
        """
        Submit customer invoice or credit note to Havano ZIMRA Cloud API.
        POST /api/method/havanozimracloud.api.sendinvoice
        """
        if not self.base_url or not self.device_sn:
            raise HavanoClientException("ZIMRA Base URL and Device Serial Number (EFD SN) are required")
        if not self.api_key or not self.api_secret:
            raise HavanoClientException("ZIMRA API Key and API Secret are required")

        session = requests.Session()
        ok, token_or_err = self.fetch_csrf_token(session)
        if not ok:
            raise HavanoClientException(f"ZIMRA CSRF Token Error: {token_or_err}")

        csrf_token = token_or_err
        send_url = f"{self.base_url}/api/method/havanozimracloud.api.sendinvoice"
        headers = {
            "X-Frappe-CSRF-Token": csrf_token,
            "Authorization": f"token {self.api_key}:{self.api_secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        partner = move.partner_id
        is_walkin = not partner or (partner.name or '').strip().lower() in ('walk-in customer', 'walk in', 'walk-in', 'walkin')

        customer_name = partner.name if partner else "Walk-in Customer"
        trade_name = (getattr(partner, 'trade_name', None) or customer_name).strip()
        raw_tin = ''.join(c for c in (partner.fiscal_tin or getattr(partner, 'tin', '') or partner.vat or '') if c.isdigit())
        raw_vat = ''.join(c for c in (partner.fiscal_vat or partner.vat or '') if c.isdigit())

        is_vat_reg = bool(getattr(partner, 'is_vat_registered', False))
        has_b2b_tin = (len(raw_tin) == 10) and is_vat_reg
        customer_tin = raw_tin if has_b2b_tin else "2000000000"
        customer_vat = raw_vat if (len(raw_vat) == 9 and is_vat_reg) else "000000000"

        # ZIMRA B2B requires add_customer="1" only when registered with a 10-digit TIN
        add_customer_flag = "1" if (not is_walkin and has_b2b_tin) else "0"

        customer_address = (partner.street or '123 Default Street').strip()
        customer_phone = (partner.phone or partner.mobile or '0000000000').strip()
        customer_city = (partner.city or 'Harare').strip()
        customer_email = (partner.email or 'walkin@example.com').strip()
        customer_province = (partner.state_id.name if partner.state_id else 'Harare').strip()

        is_credit_note = (move.move_type == 'out_refund')
        invoice_flag = "1" if is_credit_note else "0"

        currency = (move.currency_id.name or 'USD').upper()
        if currency in ('ZWD', 'ZWL', 'ZWG'):
            currency = 'ZIG'

        original_invoice_no = ""
        global_invoice_no = ""
        if is_credit_note and move.reversed_entry_id:
            original_invoice_no = move.reversed_entry_id.name or ""
            global_invoice_no = move.reversed_entry_id.fiscal_global_no or ""

        tendered = abs(float(move.amount_total or 0.0))
        items_xml = self.build_items_xml(move.invoice_line_ids, is_vat_registered=is_vat_registered)

        payload = {
            "device_sn": str(self.device_sn),
            "add_customer": add_customer_flag,
            "invoice_flag": str(invoice_flag),
            "currency": str(currency),
            "invoice_number": str(move.name or f"INV-{move.id}"),
            "customer_name": str(customer_name),
            "trade_name": str(trade_name),
            "customer_vat_number": str(customer_vat),
            "customer_address": str(customer_address),
            "customer_telephone_number": str(customer_phone),
            "customer_tin": str(customer_tin),
            "customer_province": str(customer_province),
            "customer_street": str(customer_address),
            "customer_houseNo": "1",
            "customer_city": str(customer_city),
            "customer_email": str(customer_email),
            "invoice_comment": str(move.ref or ''),
            "original_invoice_no": str(original_invoice_no),
            "global_invoice_no": str(global_invoice_no),
            "tendered": f"{tendered:.2f}",
            "items_xml": items_xml,
        }

        try:
            resp = session.post(send_url, data=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 401:
                raise HavanoClientException("ZIMRA Authentication Error: Invalid or missing API Key / Secret")
            if resp.status_code != 200:
                raise HavanoClientException(f"HTTP {resp.status_code}: {resp.text[:250]}")

            res_json = resp.json()
            msg = res_json.get("message", res_json)

            if isinstance(msg, dict):
                qr_code = str(msg.get("QRcode") or msg.get("qr_code") or "")
                ver_code = str(msg.get("VerificationCode") or msg.get("verification_code") or "")
                device_id = str(msg.get("DeviceID") or msg.get("device_id") or "")
                fiscal_day = str(msg.get("FiscalDay") or msg.get("fiscal_day") or "")
                receipt_counter = int(msg.get("receiptCounter") or msg.get("receipt_counter") or 0)
                global_no = str(msg.get("receiptGlobalNo") or msg.get("receipt_global_no") or "")

                if qr_code or ver_code or global_no:
                    return {
                        'success': True,
                        'qr_code': qr_code,
                        'verification_code': ver_code,
                        'receipt_counter': receipt_counter,
                        'receipt_global_no': global_no,
                        'device_id': device_id,
                        'device_serial': self.device_sn,
                        'fiscal_day_no': fiscal_day,
                        'raw': res_json,
                    }

            raise HavanoClientException(f"Fiscalization rejected by Havano Cloud: {resp.text[:250]}")
        except requests.exceptions.RequestException as e:
            raise HavanoClientException(f"ZIMRA Connection Error: {e}")

    def process_offline(self, move) -> dict:
        """
        Generate local SHA-256 signature hash and verification URL for offline fallback mode
        exactly as in havanoposdesk_odoo.
        """
        date_str = datetime.now().strftime("%Y%m%d%H%M%S")
        raw_str = f"{self.device_sn}{date_str}{move.id}{move.amount_total:.2f}"
        sig_hash = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()[:16].upper()
        local_url = f"https://zimra.gov.zw/verify?sn={self.device_sn}&no={move.id}&hash={sig_hash}"

        return {
            'success': True,
            'qr_code': local_url,
            'verification_code': sig_hash,
            'receipt_counter': 0,
            'receipt_global_no': str(move.id),
            'device_id': 'OFFLINE',
            'device_serial': self.device_sn,
            'fiscal_day_no': datetime.now().strftime("%Y-%m-%d"),
            'raw': {'offline': True, 'hash': sig_hash},
        }
