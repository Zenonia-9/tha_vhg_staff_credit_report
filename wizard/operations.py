import base64
import io

import xlsxwriter
from dateutil.relativedelta import relativedelta

from odoo import Command, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..models.staff_credit import CATEGORIES


class CreditOperation(models.TransientModel):
    _name = 'tha.staff.credit.operation'
    _description = 'Staff Credit Export / Monthly Deductions'
    _check_company_auto = True

    mode = fields.Selection([('export', 'Export Excel'), ('deductions', 'Generate Monthly Deductions')],
                            required=True, default='export')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    month = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(day=1))
    employee_id = fields.Many2one('hr.employee.public', check_company=True)
    department_id = fields.Many2one('hr.department', check_company=True)
    category = fields.Selection(CATEGORIES)
    status = fields.Selection([('all', 'All'), ('open', 'Open at month end'), ('settled', 'Settled at month end')],
                              default='all', required=True)
    file_data = fields.Binary(attachment=False, readonly=True)
    filename = fields.Char(readonly=True)

    def _bills(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select an allowed company.'))
        start = self.month.replace(day=1)
        domain = [('company_id', '=', self.company_id.id), ('charge_date', '<=', fields.Date.end_of(start, 'month'))]
        if self.employee_id:
            domain.append(('employee_id', '=', self.employee_id.id))
        if self.mode == 'export':
            if self.department_id:
                domain.append(('department_id', '=', self.department_id.id))
            if self.category:
                domain.append(('category', '=', self.category))
        return self.env['tha.staff.credit'].search(domain, order='department_id, employee_id, charge_date, id')

    def _rows(self):
        self.ensure_one()
        start, end = self.month.replace(day=1), fields.Date.end_of(self.month, 'month')
        rows = []
        for bill in self._bills():
            settled = bill._settled_at(end)
            balance = bill.amount - settled
            zero = bill.currency_id.is_zero(balance)
            if (self.status == 'open' and zero) or (self.status == 'settled' and not zero):
                continue
            plan = bill.schedule_ids.sorted(lambda s: (s.due_date, s.id))
            current = plan.filtered(lambda s: start <= s.due_date <= end)
            times = '%s/%s' % (list(plan).index(current) + 1, len(plan)) if current else ''
            rows.append([len(rows) + 1, bill.charge_date, bill.employee_id.name, bill.department_id.name,
                         bill.description, bill.amount, settled, times, sum(current.mapped('amount')), balance,
                         bill.remark or '', bill.name, bill.anzer_reference or '', bill.source_move_id.name])
        return rows

    def _xlsx(self):
        self.ensure_one()
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
        header = book.add_format({'bold': True, 'bg_color': '#BDD7EE', 'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
        text = book.add_format({'border': 1, 'text_wrap': True, 'valign': 'top'})
        money = book.add_format({'border': 1, 'num_format': '#,##0.00;[Red](#,##0.00);-'})
        date = book.add_format({'border': 1, 'num_format': 'dd-mmm-yyyy'})
        sheet = book.add_worksheet('Staff Credit Report')
        label = self.month.strftime("%b'%y")
        sheet.merge_range(0, 0, 0, 13, '%s - Staff Credit Report - %s' % (self.company_id.name, label), header)
        sheet.merge_range(1, 0, 1, 13, 'Currency: %s | Month amount is planned; settlement and balance include posted entries through month-end.' % self.company_id.currency_id.name, text)
        headings = ['No', 'Date', 'Staff name', 'Department', 'Name (Patient & Others)', '100% Bill',
                    'Settlement up to ' + label, 'Times', label, 'Balance for ' + label,
                    'Remark', 'System Reference', 'Anzer System invoice', 'Odoo System invoice']
        sheet.write_row(3, 0, headings, header)
        rows = self._rows()
        for number, row in enumerate(rows, 4):
            for col, value in enumerate(row):
                sheet.write(number, col, value, money if col in (5, 6, 8, 9) else date if col == 1 else text)
        total = 4 + len(rows)
        sheet.write(total, 0, 'Total', header)
        for col in (5, 6, 8, 9):
            sheet.write_number(total, col, sum(row[col] for row in rows), money)
        sheet.set_column(0, 0, 6)
        sheet.set_column(1, 1, 15)
        sheet.set_column(2, 3, 24)
        sheet.set_column(4, 4, 45)
        sheet.set_column(5, 9, 20)
        sheet.set_column(7, 7, 10)
        sheet.set_column(10, 13, 28)
        sheet.set_row(3, 48)
        sheet.freeze_panes(4, 4)
        sheet.autofilter(3, 0, max(3, total - 1), 13)
        sheet.set_landscape()
        sheet.set_paper(8)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, 3)
        sheet.print_area(0, 0, total, 13)
        book.close()
        return output.getvalue()

    def action_export(self):
        self.ensure_one()
        self.write({'file_data': base64.b64encode(self._xlsx()),
                    'filename': 'staff_credit_%s.xlsx' % self.month.strftime('%Y_%m')})
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s/%s/file_data/%s?download=true' %
                (self._name, self.id, self.filename), 'target': 'self'}

    def action_generate(self):
        self.ensure_one()
        if (not self.env.user.has_group('tha_vhg_staff_credit_report.group_manager')
                or not self.env.user.has_group('account.group_account_user')):
            raise AccessError(_('Monthly deduction generation requires Staff Credit Manager and Accounting access.'))
        self.mode = 'deductions'
        bills = self._bills()
        config = self.env['tha.staff.credit.config'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not config:
            raise UserError(_('Configure Staff Credit Settings first.'))
        config._serialize()
        start = self.month.replace(day=1)
        moves = self.env['account.move']
        batches = self.env['tha.staff.credit.batch']
        schedules = self.env['tha.staff.credit.schedule'].search([
            ('credit_id', 'in', bills.ids), ('month', '=', start)], order='credit_id, id')
        for employee in schedules.credit_id.employee_id:
            batch = batches.search([('company_id', '=', self.company_id.id), ('employee_id', '=', employee.id),
                                    ('month', '=', start)], limit=1)
            if batch.move_id:
                moves |= batch.move_id
                continue
            selected = schedules.filtered(lambda s: s.credit_id.employee_id == employee)
            if selected.deduction_line_ids:
                raise UserError(_('Some installments already have deduction links. Review the existing entries.'))
            for bill in selected.credit_id:
                if bill.currency_id.compare_amounts(sum(bill.schedule_ids.mapped('amount')), bill.amount) != 0:
                    raise UserError(_('The repayment plan for %s must total its original bill.', bill.name))
                if len(bill.schedule_ids) != bill.installment_count:
                    raise UserError(_('The installment count for %s differs from its plan.', bill.name))
            if not batch:
                batch = batches.create({'company_id': self.company_id.id, 'employee_id': employee.id, 'month': start})
            total = sum(selected.mapped('amount'))
            move = self.env['account.move'].create({
                'company_id': self.company_id.id, 'journal_id': config.journal_id.id,
                'date': fields.Date.end_of(start, 'month'), 'tha_staff_credit_batch_id': batch.id,
                'ref': 'Staff Credit - %s - %s' % (employee.name, start.strftime('%Y-%m')),
                'line_ids': [Command.create({'name': 'Staff Credit salary deduction - %s' % employee.name,
                                             'account_id': config.salary_account_id.id, 'debit': total})] + [
                    Command.create({'name': '%s - %s' % (s.credit_id.name, s.credit_id.description),
                                    'account_id': s.credit_id.source_line_id.account_id.id,
                                    'partner_id': s.credit_id.partner_id.id, 'credit': s.amount,
                                    'date_maturity': fields.Date.end_of(start, 'month'),
                                    'tha_staff_credit_id': s.credit_id.id, 'tha_staff_credit_schedule_id': s.id})
                    for s in selected],
            })
            batch.move_id = move
            selected.credit_id._check_capacity()
            for bill in selected.credit_id:
                bill.message_post(body=_('Created monthly deduction draft: %s', move.ref))
            moves |= move
        if not moves:
            raise UserError(_('No installments are scheduled for this company/staff and month.'))
        return {'type': 'ir.actions.act_window', 'name': _('Staff Credit Monthly Deductions'),
                'res_model': 'account.move', 'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)],
                'context': {'create': False}}
