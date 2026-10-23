# -*- coding: utf-8 -*-
"""
account_move.py
Extends standard Odoo account.move for direct ZIMRA fiscalization via:
- Axis Virtual Device REST API
- Havano ZIMRA Cloud API
Operates on Customer Invoices (out_invoice) and Customer Credit Notes (out_refund).
"""

import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .axis_client import AxisClientException
from .havano_client import HavanoClientException

_logger = logging.getLogger(__name__)

DEFAULT_HS_CODE = "99999999"


class AccountMove(models.Model):
    _inherit = 'account.move'

    fiscal_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending Sync'),
        ('fiscalized', 'Fiscalized'),
        ('failed', 'Fiscalization Failed'),
    ], string='Fiscal Status', default='not_required', copy=False, index=True)

    fiscal_enabled = fields.Boolean(
        related='company_id.fiscal_enabled',
        string='Fiscalization Enabled',
        readonly=True,
    )
    # Backward compatibility
    axis_enabled = fields.Boolean(
        related='company_id.fiscal_enabled',
        string='Fiscalization Enabled (Legacy Alias)',
        readonly=True,
    )

    fiscal_qr_code = fields.Text(string='ZIMRA Verification URL / QR', copy=False)
    fiscal_verification_code = fields.Char(string='Verification Code', copy=False, index=True)
    fiscal_receipt_counter = fields.Integer(string='Receipt Counter', copy=False)
    fiscal_global_no = fields.Char(string='ZIMRA Global Receipt No', copy=False, index=True)
    fiscal_device_id = fields.Char(string='Device ID', copy=False)
    fiscal_device_serial = fields.Char(string='EFD Device Serial', copy=False)
    fiscal_day_no = fields.Char(string='Fiscal Day Number', copy=False)
    fiscal_error = fields.Text(string='Fiscalization Error', copy=False)
    fiscal_request_payload = fields.Text(string='Fiscal Request Payload', copy=False)
    fiscal_response_payload = fields.Text(string='Fiscal Response Payload', copy=False)

    partner_fiscal_tin = fields.Char(
        string='Buyer ZIMRA TIN',
        related='partner_id.fiscal_tin',
        readonly=True,
        help="Customer's 10-digit ZIMRA TIN"
    )
    partner_fiscal_vat = fields.Char(
        string='Buyer ZIMRA VAT No.',
        related='partner_id.fiscal_vat',
        readonly=True,
        help="Customer's 9-digit ZIMRA VAT Number"
    )
    partner_trade_name = fields.Char(
        string='Buyer Trade Name',
        related='partner_id.trade_name',
        readonly=True,
        help="Customer's Trading As / Trade Name"
    )

    is_fiscalized = fields.Boolean(
        string='Is Fiscalized',
        compute='_compute_is_fiscalized',
        store=True,
    )

    @api.depends('fiscal_status')
    def _compute_is_fiscalized(self):
        for move in self:
            move.is_fiscalized = (move.fiscal_status == 'fiscalized')

    def _post(self, soft=True):
        """
        Hook into standard Odoo posting to trigger fiscalization upon invoice/credit note confirmation.
        """
        posted = super()._post(soft=soft)
        for move in posted:
            if move.move_type in ('out_invoice', 'out_refund'):
                if move.company_id.fiscal_enabled:
                    try:
                        move._trigger_fiscalization()
                    except Exception as e:
                        _logger.error("[FISCAL] Auto-fiscalization failed on %s: %s", move.name, e)
                        move.write({
                            'fiscal_status': 'failed',
                            'fiscal_error': str(e),
                        })
                else:
                    move.write({'fiscal_status': 'not_required'})
        return posted

    def _prepare_axis_lines(self, is_credit_note=False):
        """Build the receiptLines array conforming strictly to Axis JSON schema."""
        self.ensure_one()
        tax_inclusive = self.company_id.fiscal_tax_inclusive
        lines = []

        counter = 1
        for line in self.invoice_line_ids:
            if line.display_type not in (False, 'product'):
                continue
            if line.quantity == 0 and line.price_unit == 0:
                continue

            product = line.product_id
            raw_hs = (
                getattr(product, 'hs_code', None)
                or getattr(product, 'default_code', None)
                or getattr(product, 'barcode', None)
                or ""
            )
            hs_digits = ''.join(c for c in str(raw_hs) if c.isdigit())
            hs_code = hs_digits if len(hs_digits) >= 6 else DEFAULT_HS_CODE

            taxes = line.tax_ids.flatten_taxes_hierarchy() if hasattr(line.tax_ids, 'flatten_taxes_hierarchy') else line.tax_ids
            tax_rate = sum(t.amount for t in taxes if t.amount_type == 'percent') if taxes else 0.0

            if tax_rate == 0.0:
                tax_code = "B"
            elif abs(tax_rate - 5.0) < 0.1:
                tax_code = "C"
            elif abs(tax_rate - 15.5) < 0.1:
                tax_code = "D"
            else:
                tax_code = "A"

            qty = abs(float(line.quantity or 1.0))
            price_unit = abs(float(line.price_unit or 0.0))
            line_total = abs(float(line.price_total if tax_inclusive else line.price_subtotal))

            if is_credit_note:
                qty = -1.0 * qty
                price_unit = -1.0 * price_unit
                line_total = -1.0 * line_total

            item_name = (line.name or (product and product.name) or 'Standard Item').split('\n')[0][:100]

            lines.append({
                "receiptLineType": "Sale",
                "receiptLineNo": counter,
                "receiptLineHSCode": hs_code,
                "receiptLineName": item_name,
                "receiptLinePrice": round(price_unit, 2),
                "receiptLineQuantity": round(qty, 2),
                "receiptLineTotal": round(line_total, 2),
                "taxCode": tax_code,
                "taxPercent": round(tax_rate, 2),
            })
            counter += 1

        return lines

    def _prepare_axis_payload(self):
        """Construct the complete JSON payload for Axis Virtual Device."""
        self.ensure_one()
        company = self.company_id
        partner = self.partner_id
        is_credit_note = (self.move_type == 'out_refund')

        curr = (self.currency_id.name or 'USD').upper()
        if curr in ('ZWD', 'ZWL', 'ZWG'):
            curr = 'ZIG'

        money_type = "Cash"

        # Buyer info with safe fallbacks for required Axis REST fields
        buyer_name = (partner.commercial_partner_id.name or partner.name or 'Walk-in Customer').strip()
        buyer_trade_name = (partner.trade_name or buyer_name).strip()
        raw_tin = ''.join(c for c in (partner.fiscal_tin or getattr(partner, 'tin', '') or partner.vat or '') if c.isdigit())
        is_vat_reg = bool(getattr(partner, 'is_vat_registered', False))
        buyer_tin = raw_tin if (len(raw_tin) == 10 and is_vat_reg) else 'N/A'
        buyer_vat = raw_vat if (len(raw_vat) == 9 and is_vat_reg) else 'N/A'
        buyer_phone = (partner.phone or partner.mobile or '0770000000').strip() or '0770000000'
        buyer_email = (partner.email or 'customer@company.com').strip() or 'customer@company.com'
        buyer_city = (partner.city or 'Harare').strip() or 'Harare'
        buyer_street = (partner.street or 'Main Street').strip() or 'Main Street'
        buyer_province = (partner.state_id.name if partner.state_id else 'Harare').strip() or 'Harare'

        receipt_lines = self._prepare_axis_lines(is_credit_note=is_credit_note)

        if is_credit_note:
            invoice_amount = -1.0 * abs(round(self.amount_total, 2))
            invoice_tax = -1.0 * abs(round(self.amount_tax, 2))
            receipt_type = "CreditNote"
        else:
            invoice_amount = abs(round(self.amount_total, 2))
            invoice_tax = abs(round(self.amount_tax, 2))
            receipt_type = "FiscalInvoice"

        payload = {
            "receiptType": receipt_type,
            "receiptCurrency": curr,
            "invoiceNo": self.name or f"INV-{self.id}",
            "referenceNumber": self.name or f"INV-{self.id}",
            "invoiceAmount": invoice_amount,
            "invoiceTaxAmount": invoice_tax,
            "receiptNotes": self.ref or (f"Credit Note for {self.reversed_entry_id.name}" if is_credit_note and self.reversed_entry_id else "Sales Invoice"),
            "receiptLinesTaxInclusive": company.fiscal_tax_inclusive,
            "moneyTypeCode": money_type,
            "receiptPrintForm": "Receipt48",
            "buyerRegisterName": buyer_name,
            "buyerTradeName": buyer_trade_name,
            "vatNumber": buyer_vat,
            "buyerTIN": buyer_tin,
            "buyerPhoneNo": buyer_phone,
            "buyerEmail": buyer_email,
            "buyerCity": buyer_city,
            "buyerStreet": buyer_street,
            "buyerHouseNo": "1",
            "buyerProvince": buyer_province,
            "receiptDate": fields.Datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "receiptLines": receipt_lines,
        }

        if is_credit_note:
            orig = self.reversed_entry_id
            payload["refReceiptGlobalnumber"] = orig.fiscal_global_no if orig and orig.fiscal_global_no else ""
            payload["refDeviceID"] = orig.fiscal_device_id if orig and orig.fiscal_device_id else (company.axis_device_id or "")
            payload["refFiscalDay"] = orig.fiscal_day_no if orig and orig.fiscal_day_no else (company.axis_current_fiscal_day or "")

        return payload

    def _trigger_axis_fiscalization(self):
        """Execute HTTP transmission to Axis Virtual Device API."""
        company = self.company_id
        client = company.get_axis_client()

        if company.axis_auto_open_day:
            try:
                status = client.get_status()
                day_status = (status.get('fiscal_day_status') or '').strip().lower()
                company.sudo().write({
                    'axis_current_fiscal_day': status.get('fiscal_day_no'),
                    'axis_fiscal_day_status': status.get('fiscal_day_status'),
                })
                if day_status == 'closed':
                    _logger.info("[AXIS] Fiscal Day is closed. Auto-opening fiscal day...")
                    client.open_fiscal_day()
            except Exception as e:
                _logger.warning("[AXIS] Could not verify/open fiscal day: %s", e)

        payload = self._prepare_axis_payload()
        self.fiscal_request_payload = json.dumps(payload, indent=2)

        is_credit_note = (self.move_type == 'out_refund')
        if is_credit_note:
            res = client.submit_receipt_ext(payload)
        else:
            res = client.submit_receipt(payload)

        self.write({
            'fiscal_status': 'fiscalized',
            'fiscal_qr_code': res.get('qr_code', ''),
            'fiscal_verification_code': res.get('verification_code', ''),
            'fiscal_receipt_counter': res.get('receipt_counter', 0),
            'fiscal_global_no': res.get('receipt_global_no', ''),
            'fiscal_device_id': res.get('device_id', ''),
            'fiscal_device_serial': res.get('device_serial', ''),
            'fiscal_day_no': res.get('fiscal_day_no', ''),
            'fiscal_error': False,
            'fiscal_response_payload': json.dumps(res.get('raw', {}), indent=2),
        })

    def _trigger_havano_fiscalization(self):
        """Execute HTTP transmission to Havano ZIMRA Cloud API."""
        company = self.company_id
        client = company.get_havano_client()

        res = client.submit_invoice(self, is_vat_registered=company.fiscal_tax_inclusive)
        self.write({
            'fiscal_status': 'fiscalized',
            'fiscal_qr_code': res.get('qr_code', ''),
            'fiscal_verification_code': res.get('verification_code', ''),
            'fiscal_receipt_counter': res.get('receipt_counter', 0),
            'fiscal_global_no': res.get('receipt_global_no', ''),
            'fiscal_device_id': res.get('device_id', ''),
            'fiscal_device_serial': res.get('device_serial', ''),
            'fiscal_day_no': res.get('fiscal_day_no', ''),
            'fiscal_error': False,
            'fiscal_response_payload': json.dumps(res.get('raw', {}), indent=2),
        })

    def _trigger_fiscalization(self):
        """Dispatches to the configured fiscal provider (Axis or Havano)."""
        self.ensure_one()
        company = self.company_id
        if not company.fiscal_enabled:
            self.write({'fiscal_status': 'not_required'})
            return

        try:
            if company.fiscal_provider == 'axis':
                self._trigger_axis_fiscalization()
            elif company.fiscal_provider == 'havano_zimra':
                self._trigger_havano_fiscalization()
            else:
                raise UserError(_("Unknown fiscal provider: %s") % company.fiscal_provider)

            _logger.info("[FISCAL] Successfully fiscalized %s as Global No %s", self.name, self.fiscal_global_no)
        except (AxisClientException, HavanoClientException) as e:
            self.write({
                'fiscal_status': 'failed',
                'fiscal_error': str(e),
            })
            raise

    def action_axis_fiscalize(self):
        """User button to manually submit or retry fiscalization."""
        return self.action_fiscalize()

    def action_fiscalize(self):
        """User button to manually submit or retry fiscalization."""
        for move in self:
            if not move.company_id.fiscal_enabled:
                raise UserError(_("Fiscalization is turned OFF. Turn it on in Settings to start fiscalizing."))
            if move.state != 'posted':
                raise UserError(_("You can only fiscalize posted invoices and credit notes."))
            if move.move_type not in ('out_invoice', 'out_refund'):
                raise UserError(_("Fiscalization is only supported for Customer Invoices and Credit Notes."))
            try:
                move._trigger_fiscalization()
            except Exception as e:
                raise UserError(_("Fiscalization Failed: %s") % str(e))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Fiscalization Successful"),
                'message': _("Document(s) successfully registered with ZIMRA."),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def cron_retry_pending_fiscalization(self):
        """Cron job to retry failed or pending fiscal records."""
        moves = self.search([
            ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('fiscal_status', 'in', ('pending', 'failed')),
            ('company_id.fiscal_enabled', '=', True),
        ], limit=30, order='id desc')

        for move in moves:
            try:
                move._trigger_fiscalization()
            except Exception as e:
                _logger.warning("[FISCAL CRON] Retry failed for %s: %s", move.name, e)
