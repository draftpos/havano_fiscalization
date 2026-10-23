{
    'name': 'ZIMRA Fiscalization (Axis & Havano Cloud)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Fiscalization',
    'summary': 'ZIMRA Fiscalization for standard Odoo Invoices and Credit Notes via Axis Virtual Device & Havano Cloud',
    'description': """
ZIMRA Fiscalization for Standard Odoo (Axis & Havano Cloud)
===========================================================
This module provides complete ZIMRA (Zimbabwe Revenue Authority) FDMS compliance for standard Odoo Invoicing and Credit Notes (`account.move`), supporting:

1. **Axis Virtual Device REST API**:
   - Automated authentication via JWT Bearer Token.
   - Standard Invoices submitted to `/api/VirtualDevice/SubmitReceipt`.
   - Credit Notes submitted to `/api/VirtualDevice/SubmitReceiptExt` (negative numbers, original invoice references).
   - Auto-detected Device ID and EFD Serial Number.
   - Fiscal Day management (Open Fiscal Day & Close Fiscal Day with Z-Report).

2. **Havano ZIMRA Cloud API**:
   - 2-Tier authentication (CSRF Token + API Token).
   - Structured XML line items with ZIMRA VAT classification codes.
   - Device ping and real-time electronic invoice submission.

3. **General Features**:
   - Master switch: Invoicing only fiscalizes when explicitly enabled in Settings (`fiscal_enabled`).
   - Default testing credentials pre-configured for immediate testing.
   - ZIMRA Verification details (QR Code, Global Invoice No, Verification Code, Device Serial) printed directly on standard PDF invoices and credit notes.
   - Zero dependencies on custom POS modules.
    """,
    'author': 'Havano ERP',
    'website': 'https://havano.online',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_data.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/fiscal_day_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
        'report/invoice_report_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
