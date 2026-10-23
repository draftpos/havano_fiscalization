# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AxisFiscalDay(models.Model):
    _name = 'axis.fiscal.day'
    _description = 'Axis Fiscal Day & Z-Report Record'
    _order = 'id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    fiscal_day_no = fields.Char(string='Fiscal Day Number', required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    state = fields.Selection([
        ('open', 'Open'),
        ('closed', 'Closed (Z-Report Issued)')
    ], string='Status', default='open', required=True)
    opened_at = fields.Datetime(string='Opened At', default=fields.Datetime.now)
    closed_at = fields.Datetime(string='Closed At')
    z_report_response = fields.Text(string='Z-Report Raw Data')
    invoice_count = fields.Integer(string='Invoices Fiscalized', compute='_compute_stats')
    credit_note_count = fields.Integer(string='Credit Notes Fiscalized', compute='_compute_stats')

    @api.depends('fiscal_day_no', 'company_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"Fiscal Day #{rec.fiscal_day_no or 'Draft'}"

    def _compute_stats(self):
        for rec in self:
            rec.invoice_count = self.env['account.move'].search_count([
                ('company_id', '=', rec.company_id.id),
                ('fiscal_day_no', '=', rec.fiscal_day_no),
                ('move_type', '=', 'out_invoice'),
                ('fiscal_status', '=', 'fiscalized'),
            ])
            rec.credit_note_count = self.env['account.move'].search_count([
                ('company_id', '=', rec.company_id.id),
                ('fiscal_day_no', '=', rec.fiscal_day_no),
                ('move_type', '=', 'out_refund'),
                ('fiscal_status', '=', 'fiscalized'),
            ])

    def action_close_day(self):
        self.ensure_one()
        return self.company_id.action_axis_close_fiscal_day()
