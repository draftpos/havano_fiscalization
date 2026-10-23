# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import re


class ResPartner(models.Model):
    _inherit = 'res.partner'

    fiscal_tin = fields.Char(
        string='ZIMRA TIN',
        size=10,
        help="10-digit Zimbabwe Taxpayer Identification Number (e.g. 2000000000). Required by ZIMRA for B2B buyers."
    )
    fiscal_vat = fields.Char(
        string='ZIMRA VAT Number',
        size=9,
        help="9-digit Value Added Tax Registration Number (e.g. 100000000). Required if registered for VAT in Zimbabwe."
    )
    trade_name = fields.Char(
        string='Trade Name (Trading As)',
        help="Customer's business trading name / DBA (e.g. Acme Supermarket) used for ZIMRA fiscalization."
    )
    is_vat_registered = fields.Boolean(
        string='Is VAT Registered?',
        default=False,
        help="Check if this business partner is officially registered for VAT in Zimbabwe."
    )

    @api.onchange('fiscal_tin')
    def _onchange_fiscal_tin(self):
        if self.fiscal_tin:
            cleaned = re.sub(r'\D', '', self.fiscal_tin)
            self.fiscal_tin = cleaned[:10]

    @api.onchange('fiscal_vat')
    def _onchange_fiscal_vat(self):
        if self.fiscal_vat:
            cleaned = re.sub(r'\D', '', self.fiscal_vat)
            self.fiscal_vat = cleaned[:9]
            if len(self.fiscal_vat) == 9:
                self.is_vat_registered = True
                if not self.vat:
                    self.vat = self.fiscal_vat

    @api.onchange('vat')
    def _onchange_vat_sync_fiscal(self):
        """Auto-populate fiscal_tin or fiscal_vat from standard Odoo Tax ID if empty."""
        if self.vat:
            digits = re.sub(r'\D', '', self.vat)
            if len(digits) == 10 and not self.fiscal_tin:
                self.fiscal_tin = digits
            elif len(digits) == 9 and not self.fiscal_vat:
                self.fiscal_vat = digits
                self.is_vat_registered = True

    @api.constrains('fiscal_tin')
    def _check_fiscal_tin(self):
        for partner in self:
            if partner.fiscal_tin:
                digits = re.sub(r'\D', '', partner.fiscal_tin)
                if len(digits) != 10:
                    raise ValidationError(_("ZIMRA TIN must be exactly 10 digits (e.g. 2000000000). Found: '%s'") % partner.fiscal_tin)

    @api.constrains('fiscal_vat')
    def _check_fiscal_vat(self):
        for partner in self:
            if partner.fiscal_vat:
                digits = re.sub(r'\D', '', partner.fiscal_vat)
                if len(digits) != 9:
                    raise ValidationError(_("ZIMRA VAT Number must be exactly 9 digits (e.g. 100000000). Found: '%s'") % partner.fiscal_vat)
