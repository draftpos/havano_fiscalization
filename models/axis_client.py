# -*- coding: utf-8 -*-
"""
Axis Virtual Device REST API Client
Implements authoritative communication with Axis Virtual Device & ZIMRA FDMS.
Handles JWT authentication, automatic token renewal, day management,
invoice submission, and credit note submission with negative values & references.
"""

import json
import logging
import requests

_logger = logging.getLogger(__name__)


class AxisClientException(Exception):
    """Custom exception for Axis API errors."""
    pass


class AxisVirtualDeviceClient:
    """
    HTTP Client for Axis Virtual Device REST API.
    """

    def __init__(self, base_url: str, email: str, password: str, device_id: str = None, token: str = None, timeout: int = 15):
        self.base_url = (base_url or '').rstrip('/')
        self.email = email or ''
        self.password = password or ''
        self.device_id = device_id or ''
        self.token = token or ''
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self, auth: bool = True) -> dict:
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if auth and self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def login(self) -> str:
        """
        Authenticate against /api/Auth/login and obtain JWT Bearer Token.
        """
        if not self.base_url:
            raise AxisClientException("Axis Server Base URL is required.")
        if not self.email or not self.password:
            raise AxisClientException("Axis API User Email and Password are required.")

        url = f"{self.base_url}/api/Auth/login"
        payload = {
            "email": self.email,
            "password": self.password,
        }

        _logger.info("[AXIS] Authenticating user %s at %s", self.email, url)
        try:
            resp = self.session.post(url, json=payload, headers=self._headers(auth=False), timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise AxisClientException(f"Connection to Axis Server failed: {e}")

        if resp.status_code != 200:
            raise AxisClientException(f"Authentication failed (HTTP {resp.status_code}): {resp.text[:250]}")

        try:
            data = resp.json()
        except Exception:
            raise AxisClientException(f"Invalid JSON returned from login endpoint: {resp.text[:200]}")

        token = data.get('token') or data.get('accessToken') or data.get('Token')
        if not token:
            raise AxisClientException(f"No token received in login response: {data}")

        self.token = token
        return token

    def _ensure_authenticated(self):
        if not self.token and self.email and self.password:
            self.login()

    def _request(self, method: str, endpoint: str, json_data: dict = None, retry_auth: bool = True) -> dict:
        self._ensure_authenticated()
        url = f"{self.base_url}{endpoint}"

        headers = self._headers(auth=bool(self.token))
        try:
            if method.upper() == 'GET':
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
            else:
                resp = self.session.post(url, json=json_data, headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            raise AxisClientException(f"Request to {endpoint} failed: {e}")

        # If token expired, re-login once and retry (if email & password provided)
        if resp.status_code == 401 and retry_auth and self.email and self.password:
            _logger.warning("[AXIS] Token expired or unauthorized. Re-authenticating...")
            self.login()
            return self._request(method, endpoint, json_data=json_data, retry_auth=False)

        if resp.status_code not in (200, 201):
            raise AxisClientException(f"Axis API returned HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            res_json = resp.json()
        except Exception:
            raise AxisClientException(f"Non-JSON response from {endpoint}: {resp.text[:200]}")

        return res_json

    @staticmethod
    def _extract_field(data: dict, *keys, default=None):
        """Extract first matching key ignoring casing and check nested 'Data'/'data'/'Message'."""
        search_dicts = [data]
        if isinstance(data.get('data'), dict):
            search_dicts.append(data['data'])
        if isinstance(data.get('Data'), dict):
            search_dicts.append(data['Data'])
        if isinstance(data.get('Message'), dict):
            search_dicts.append(data['Message'])
        elif isinstance(data.get('Message'), str) and data['Message'].strip().startswith('{'):
            try:
                parsed_msg = json.loads(data['Message'])
                if isinstance(parsed_msg, dict):
                    search_dicts.append(parsed_msg)
            except Exception:
                pass

        for d in search_dicts:
            for k in keys:
                if k in d and d[k] is not None:
                    return d[k]
                # Check case-insensitive
                for existing_k, val in d.items():
                    if existing_k.lower() == k.lower() and val is not None:
                        return val
        return default

    def get_config(self) -> dict:
        """
        GET /api/VirtualDevice/GetConfig
        Returns device configuration, device ID, device serial number, taxpayer info.
        """
        raw = self._request('GET', '/api/VirtualDevice/GetConfig')
        return {
            'device_id': str(self._extract_field(raw, 'DeviceID', 'deviceId', default='')),
            'device_sn': str(self._extract_field(raw, 'DeviceSerialNumber', 'deviceSerialNumber', default='')),
            'fiscal_day_no': str(self._extract_field(raw, 'FiscalDayNo', 'fiscalDayNo', default='')),
            'raw': raw,
        }

    def get_status(self) -> dict:
        """
        GET /api/VirtualDevice/GetStatus
        Returns device ID, serial, fiscal day number, and status (Open / Closed).
        """
        raw = self._request('GET', '/api/VirtualDevice/GetStatus')
        device_id = str(self._extract_field(raw, 'DeviceID', 'deviceId', default=''))
        device_sn = str(self._extract_field(raw, 'DeviceSerialNumber', 'deviceSerialNumber', default=''))
        fiscal_day_no = str(self._extract_field(raw, 'FiscalDayNo', 'fiscalDayNo', 'lastFiscalDayNo', default=''))
        fiscal_day_status = str(self._extract_field(raw, 'FiscalDayStatus', 'fiscalDayStatus', default=''))

        # Fallback to GetConfig if device ID or fiscal day number is missing in status
        if not device_id or not fiscal_day_no:
            try:
                cfg = self.get_config()
                device_id = device_id or cfg.get('device_id', '')
                device_sn = device_sn or cfg.get('device_sn', '')
                fiscal_day_no = fiscal_day_no or cfg.get('fiscal_day_no', '')
            except Exception:
                pass

        return {
            'device_id': device_id,
            'device_sn': device_sn,
            'fiscal_day_no': fiscal_day_no,
            'fiscal_day_status': fiscal_day_status,
            'raw': raw,
        }

    def open_fiscal_day(self) -> dict:
        """
        GET /api/VirtualDevice/OpenFiscalDay
        Opens the fiscal day. Treats 'already open' as successful.
        """
        raw = self._request('GET', '/api/VirtualDevice/OpenFiscalDay')
        code = str(self._extract_field(raw, 'Code', 'code', default=''))
        message = str(self._extract_field(raw, 'Message', 'message', default=''))

        is_already_open = 'already' in message.lower()
        success = (code == '1') or is_already_open

        if not success:
            raise AxisClientException(f"Failed to open fiscal day: {message}")

        return {
            'success': True,
            'message': message,
            'code': code,
            'already_open': is_already_open,
            'raw': raw,
        }

    def close_fiscal_day(self) -> dict:
        """
        GET /api/VirtualDevice/CloseFiscalDay
        Closes the active fiscal day and triggers the daily ZIMRA Z-Report.
        """
        raw = self._request('GET', '/api/VirtualDevice/CloseFiscalDay')
        code = str(self._extract_field(raw, 'Code', 'code', default=''))
        message = str(self._extract_field(raw, 'Message', 'message', default=''))

        if code != '1':
            raise AxisClientException(f"Failed to close fiscal day: {message}")

        return {
            'success': True,
            'message': message,
            'code': code,
            'raw': raw,
        }

    def submit_receipt(self, payload: dict) -> dict:
        """
        POST /api/VirtualDevice/SubmitReceipt
        For Standard Invoices (receiptType = FiscalInvoice).
        """
        raw = self._request('POST', '/api/VirtualDevice/SubmitReceipt', json_data=payload)
        return self._parse_receipt_response(raw)

    def submit_receipt_ext(self, payload: dict) -> dict:
        """
        POST /api/VirtualDevice/SubmitReceiptExt
        For Credit Notes (receiptType = CreditNote) with negative numbers and original invoice refs.
        """
        raw = self._request('POST', '/api/VirtualDevice/SubmitReceiptExt', json_data=payload)
        return self._parse_receipt_response(raw)

    def _parse_receipt_response(self, raw: dict) -> dict:
        code = str(self._extract_field(raw, 'Code', 'code', default=''))
        message = str(self._extract_field(raw, 'Message', 'message', default=''))

        if code != '1':
            raise AxisClientException(f"Fiscalization rejected by Axis (Code {code}): {message}")

        qr_code = self._extract_field(raw, 'qrCode', 'QRCode', 'QRcode', 'qr_code', default='')
        verification_code = self._extract_field(raw, 'verificationCode', 'VerificationCode', 'verification_code', default='')
        device_id = self._extract_field(raw, 'deviceId', 'DeviceID', 'device_id', default='')
        receipt_counter = self._extract_field(raw, 'receiptCounter', 'ReceiptCounter', 'receipt_counter', default=0)
        receipt_global_no = self._extract_field(raw, 'receiptGlobalNo', 'ReceiptGlobalNo', 'FDMSInvoiceNo', 'receipt_global_no', default='')
        device_serial = self._extract_field(raw, 'deviceSerialNumber', 'DeviceSerialNumber', 'device_serial_number', default='')
        fiscal_day_no = self._extract_field(raw, 'fiscalDayNo', 'FiscalDayNo', 'fiscal_day_no', default='')

        return {
            'success': True,
            'code': code,
            'message': message,
            'qr_code': str(qr_code or ''),
            'verification_code': str(verification_code or ''),
            'device_id': str(device_id or ''),
            'receipt_counter': int(receipt_counter or 0),
            'receipt_global_no': str(receipt_global_no or ''),
            'device_serial': str(device_serial or ''),
            'fiscal_day_no': str(fiscal_day_no or ''),
            'raw': raw,
        }
