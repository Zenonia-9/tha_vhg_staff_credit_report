from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Existing linked bills were already based on posted sources before the
    # lifecycle field existed.
    legacy_bills = env['tha.staff.credit'].search([
        ('source_move_id', '!=', False), ('state', '!=', 'posted'),
    ])
    legacy_bills.write({'state': 'posted'})

    # Use the requested account by code wherever that company's chart has it.
    # Leave it unset where it does not exist so a manager can select a valid
    # company income account in Settings before creating an invoice.
    for config in env['tha.staff.credit.config'].search([('invoice_credit_account_id', '=', False)]):
        account = env['account.account'].with_company(config.company_id).search([
            ('company_ids', 'in', config.company_id.id), ('code', '=', '510585'),
        ], limit=1)
        if account and account.account_type in ('income', 'income_other') and account.active:
            config.write({'invoice_credit_account_id': account.id})
