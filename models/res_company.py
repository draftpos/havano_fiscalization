# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .axis_client import AxisVirtualDeviceClient, AxisClientException
from .havano_client import HavanoZimraCloudClient, HavanoClientException
import logging

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    fiscal_enabled = fields.Boolean(
        string='Enable Fiscalization',
        default=False,
        help="Master switch to automate ZIMRA fiscalization for Invoices & Credit Notes."
    )
    # Backward compatibility alias
    axis_enabled = fields.Boolean(
        related='fiscal_enabled',
        readonly=False,
        string='Fiscalization Enabled (Legacy Alias)'
    )

    fiscal_provider = fields.Selection([
        ('axis', 'Axis Virtual Device'),
        ('havano_zimra', 'Havano ZIMRA Cloud')
    ], string='Fiscal Provider', default='axis', required=True)

    fiscal_trade_name = fields.Char(
        string='Fiscal Trade Name (Trading As)',
        help="Trading/Business name used for ZIMRA fiscalization instead of the legal company name."
    )

    fiscal_tax_inclusive = fields.Boolean(
        string='Prices Tax Inclusive',
        default=True,
        help="Set to True if your product selling prices are inclusive of VAT."
    )
    axis_tax_inclusive = fields.Boolean(
        related='fiscal_tax_inclusive',
        readonly=False,
        string='Prices Tax Inclusive (Legacy Alias)'
    )

    # -------------------------------------------------------------
    # Axis Virtual Device Settings
    # -------------------------------------------------------------
    axis_base_url = fields.Char(
        string='Axis Server URL',
        default='http://140.82.25.196:10007',
        help="Base URL of the Axis Virtual Device API."
    )
    axis_email = fields.Char(
        string='API User Email',
        default='webservice@axissol.com',
        help="Email address used to authenticate with Axis Virtual Device API."
    )
    axis_password = fields.Char(
        string='API Password',
        default='password',
        help="Password used to authenticate with Axis Virtual Device API."
    )
    axis_device_id = fields.Char(
        string='Device ID',
        default='21890',
        readonly=True,
        help="ZIMRA Device ID auto-detected from the Axis Virtual Device."
    )
    axis_device_sn = fields.Char(
        string='Device Serial Number',
        default='VR-D3952E09A521B918',
        readonly=True,
        help="ZIMRA EFD Serial Number auto-detected from the Axis Virtual Device."
    )
    axis_auto_open_day = fields.Boolean(
        string='Auto-Open Fiscal Day',
        default=True,
        help="Automatically open the fiscal day if closed when an invoice is confirmed."
    )
    axis_current_fiscal_day = fields.Char(
        string='Current Fiscal Day',
        readonly=True
    )
    axis_fiscal_day_status = fields.Char(
        string='Fiscal Day Status',
        readonly=True
    )

    # -------------------------------------------------------------
    # Havano ZIMRA Cloud Settings
    # -------------------------------------------------------------
    havano_base_url = fields.Char(
        string='Havano Cloud Base URL',
        default='https://erpfiscal.havano.online',
        help="Endpoint URL for Havano ZIMRA Cloud API."
    )
    havano_api_key = fields.Char(
        string='API Key',
        default='51565a611a2cdb7',
        help="API Key for Havano ZIMRA Cloud."
    )
    havano_api_secret = fields.Char(
        string='API Secret',
        default='425105201835d2c',
        help="API Secret for Havano ZIMRA Cloud."
    )
    havano_device_sn = fields.Char(
        string='Device Serial Number (EFD SN)',
        help="ZIMRA Electronic Fiscal Device Serial Number registered in Havano Cloud."
    )

    def get_axis_client(self):
        self.ensure_one()
        return AxisVirtualDeviceClient(
            base_url=self.axis_base_url,
            email=self.axis_email,
            password=self.axis_password,
            device_id=self.axis_device_id,
        )

    def get_havano_client(self):
        self.ensure_one()
        return HavanoZimraCloudClient(
            base_url=self.havano_base_url,
            api_key=self.havano_api_key,
            api_secret=self.havano_api_secret,
            device_sn=self.havano_device_sn,
        )

    def action_fiscal_test_connection(self):
        """Test API connectivity based on selected fiscal provider."""
        self.ensure_one()
        if self.fiscal_provider == 'axis':
            return self.action_axis_test_connection()
        elif self.fiscal_provider == 'havano_zimra':
            return self.action_havano_test_connection()

    def action_axis_test_connection(self):
        """Test API connectivity and retrieve device status for Axis Virtual Device."""
        self.ensure_one()
        if not self.axis_base_url:
            raise UserError(_("Please fill in the Axis Server URL."))

        client = self.get_axis_client()
        try:
            status = client.get_status()
            self.axis_current_fiscal_day = status.get('fiscal_day_no') or self.axis_current_fiscal_day
            self.axis_fiscal_day_status = status.get('fiscal_day_status') or self.axis_fiscal_day_status
            if status.get('device_id'):
                self.axis_device_id = status['device_id']
            if status.get('device_sn'):
                self.axis_device_sn = status['device_sn']

            msg = _("Axis Virtual Device Connected Successfully!\n\n"
                    "Device ID: %s\n"
                    "Serial Number: %s\n"
                    "Fiscal Day: %s\n"
                    "Day Status: %s") % (
                status.get('device_id'),
                status.get('device_sn'),
                status.get('fiscal_day_no'),
                status.get('fiscal_day_status')
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Connection Successful"),
                    'message': msg,
                    'type': 'success',
                    'sticky': True,
                }
            }
        except AxisClientException as e:
            raise UserError(_("Axis Connection Failed: %s") % str(e))

    def action_havano_test_connection(self):
        """Test API connectivity for Havano ZIMRA Cloud."""
        self.ensure_one()
        if not self.havano_base_url or not self.havano_api_key or not self.havano_api_secret or not self.havano_device_sn:
            raise UserError(_("Please fill in Havano Cloud Base URL, API Key, API Secret, and Device Serial Number."))

        client = self.get_havano_client()
        try:
            res = client.ping_device()
            data = res.get('data', {}) if isinstance(res, dict) else {}
            sn = data.get('device_sn') or self.havano_device_sn or 'OK'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Ping Successful"),
                    'message': _("Connected! Device SN: %s | Status: Online") % sn,
                    'type': 'success',
                    'sticky': False,
                }
            }
        except HavanoClientException as e:
            raise UserError(_("Havano ZIMRA Connection Failed: %s") % str(e))

    def action_axis_open_fiscal_day(self):
        """Manually open fiscal day on Axis Virtual Device."""
        self.ensure_one()
        client = self.get_axis_client()
        try:
            res = client.open_fiscal_day()
            status = client.get_status()
            self.axis_current_fiscal_day = status.get('fiscal_day_no')
            self.axis_fiscal_day_status = status.get('fiscal_day_status')

            self.env['axis.fiscal.day'].sudo().create({
                'company_id': self.id,
                'fiscal_day_no': self.axis_current_fiscal_day,
                'state': 'open',
                'opened_at': fields.Datetime.now(),
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Fiscal Day"),
                    'message': res.get('message', _("Fiscal Day opened successfully")),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except AxisClientException as e:
            raise UserError(_("Failed to open fiscal day: %s") % str(e))

    def action_axis_close_fiscal_day(self):
        """Close fiscal day and generate Z-Report on Axis Virtual Device."""
        self.ensure_one()
        client = self.get_axis_client()
        try:
            res = client.close_fiscal_day()
            status = client.get_status()
            day_no = self.axis_current_fiscal_day
            self.axis_current_fiscal_day = status.get('fiscal_day_no')
            self.axis_fiscal_day_status = status.get('fiscal_day_status')

            existing_day = self.env['axis.fiscal.day'].sudo().search([
                ('company_id', '=', self.id),
                ('fiscal_day_no', '=', day_no),
                ('state', '=', 'open')
            ], limit=1)
            if existing_day:
                existing_day.write({
                    'state': 'closed',
                    'closed_at': fields.Datetime.now(),
                    'z_report_response': str(res.get('raw', '')),
                })
            else:
                self.env['axis.fiscal.day'].sudo().create({
                    'company_id': self.id,
                    'fiscal_day_no': day_no,
                    'state': 'closed',
                    'closed_at': fields.Datetime.now(),
                    'z_report_response': str(res.get('raw', '')),
                })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Fiscal Day Closed / Z-Report"),
                    'message': res.get('message', _("Fiscal Day closed successfully. Z-Report generated.")),
                    'type': 'success',
                    'sticky': True,
                }
            }
        except AxisClientException as e:
            raise UserError(_("Failed to close fiscal day: %s") % str(e))
