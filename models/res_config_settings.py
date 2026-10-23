# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fiscal_enabled = fields.Boolean(
        related='company_id.fiscal_enabled',
        readonly=False,
        string='Enable Fiscalization'
    )
    axis_enabled = fields.Boolean(
        related='company_id.axis_enabled',
        readonly=False,
        string='Fiscalization Enabled (Legacy Alias)'
    )
    fiscal_provider = fields.Selection(
        related='company_id.fiscal_provider',
        readonly=False,
        string='Fiscal Provider'
    )
    fiscal_trade_name = fields.Char(
        related='company_id.fiscal_trade_name',
        readonly=False,
        string='Company Fiscal Trade Name (Trading As)'
    )
    fiscal_tax_inclusive = fields.Boolean(
        related='company_id.fiscal_tax_inclusive',
        readonly=False,
        string='Prices Tax Inclusive'
    )
    axis_tax_inclusive = fields.Boolean(
        related='company_id.axis_tax_inclusive',
        readonly=False,
        string='Prices Tax Inclusive (Legacy Alias)'
    )

    # Axis Specific
    axis_base_url = fields.Char(
        related='company_id.axis_base_url',
        readonly=False,
        string='Axis Server URL'
    )
    axis_email = fields.Char(
        related='company_id.axis_email',
        readonly=False,
        string='API User Email'
    )
    axis_password = fields.Char(
        related='company_id.axis_password',
        readonly=False,
        string='API Password'
    )
    axis_device_id = fields.Char(
        related='company_id.axis_device_id',
        readonly=True,
        string='Device ID'
    )
    axis_device_sn = fields.Char(
        related='company_id.axis_device_sn',
        readonly=True,
        string='Device Serial Number'
    )
    axis_auto_open_day = fields.Boolean(
        related='company_id.axis_auto_open_day',
        readonly=False,
        string='Auto-Open Fiscal Day'
    )
    axis_current_fiscal_day = fields.Char(
        related='company_id.axis_current_fiscal_day',
        readonly=True,
        string='Current Fiscal Day'
    )
    axis_fiscal_day_status = fields.Char(
        related='company_id.axis_fiscal_day_status',
        readonly=True,
        string='Fiscal Day Status'
    )

    # Havano ZIMRA Cloud Specific
    havano_base_url = fields.Char(
        related='company_id.havano_base_url',
        readonly=False,
        string='Havano Cloud Base URL'
    )
    havano_api_key = fields.Char(
        related='company_id.havano_api_key',
        readonly=False,
        string='API Key'
    )
    havano_api_secret = fields.Char(
        related='company_id.havano_api_secret',
        readonly=False,
        string='API Secret'
    )
    havano_device_sn = fields.Char(
        related='company_id.havano_device_sn',
        readonly=False,
        string='Device Serial Number (EFD SN)'
    )

    def action_fiscal_test_connection(self):
        return self.company_id.action_fiscal_test_connection()

    def action_axis_test_connection(self):
        return self.company_id.action_axis_test_connection()

    def action_havano_test_connection(self):
        return self.company_id.action_havano_test_connection()

    def action_axis_open_fiscal_day(self):
        return self.company_id.action_axis_open_fiscal_day()

    def action_axis_close_fiscal_day(self):
        return self.company_id.action_axis_close_fiscal_day()
