from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for config in env['tha.staff.credit.config'].search([('invoice_credit_account_id', '=', False)]):
        account = env['account.account'].with_company(config.company_id).search([
            ('company_ids', 'in', config.company_id.id), ('code', '=', '510585'),
        ], limit=1)
        if account and account.account_type in ('income', 'income_other') and account.active:
            config.write({'invoice_credit_account_id': account.id})
