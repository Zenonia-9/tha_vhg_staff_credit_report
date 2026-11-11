import base64
import io
import math
import textwrap

import xlsxwriter
from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError

from ..models.staff_credit import CATEGORIES


class CreditOperation(models.TransientModel):
    _name = 'tha.staff.credit.operation'
    _description = 'Staff Credit Export / Monthly Deductions'
    _check_company_auto = True

    mode = fields.Selection([('export', 'Export Excel'), ('deductions', 'Generate Monthly Deductions')],
                            required=True, default='export')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    bill_ids = fields.Many2many('tha.staff.credit', string='Selected staff credit bills', check_company=True)
    employee_ids = fields.Many2many('hr.employee.public', compute='_compute_employee_ids', string='Employees', readonly=True)
    month = fields.Date(string='Month (leave blank for all)')
    date_from = fields.Date(string='Charge date from')
    date_to = fields.Date(string='Charge date to')
    employee_id = fields.Many2one('hr.employee.public', check_company=True)
    department_id = fields.Many2one('hr.department', check_company=True)
    category = fields.Selection(CATEGORIES)
    status = fields.Selection([('all', 'All'), ('open', 'Open at month end'), ('settled', 'Settled at month end')],
                              default='all', required=True)
    account_id = fields.Many2one('account.account', string='Staff Credit account', check_company=True)
    salary_account_id = fields.Many2one('account.account',
        string='Salary expense / Cash-Bank clearing account', check_company=True)
    journal_id = fields.Many2one('account.journal', string='Deduction journal', check_company=True)
    file_data = fields.Binary(attachment=False, readonly=True)
    filename = fields.Char(readonly=True)

    @api.depends('bill_ids.employee_id')
    def _compute_employee_ids(self):
        for operation in self:
            operation.employee_ids = operation.bill_ids.employee_id

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        if values.get('mode', self.env.context.get('default_mode')) == 'deductions' and 'month' in names:
            if not values.get('month'):
                values['month'] = fields.Date.context_today(self).replace(day=1)
        if values.get('mode', self.env.context.get('default_mode')) == 'deductions' and 'bill_ids' in names:
            ids = self.env.context.get('active_ids') or [self.env.context.get('active_id')]
            bills = self.env['tha.staff.credit'].browse([i for i in ids if i]).exists() if self.env.context.get('active_model') == 'tha.staff.credit' else self.env['tha.staff.credit']
            bills.check_access('read')
            if len(bills.company_id) > 1:
                raise UserError(_('Select staff credit bills from one company at a time.'))
            values['bill_ids'] = [Command.set(bills.ids)]
            if bills:
                values['company_id'] = bills.company_id.id
        elif values.get('mode', self.env.context.get('default_mode')) == 'export':
            ids = self.env.context.get('active_ids') or [self.env.context.get('active_id')]
            if self.env.context.get('active_model') == 'tha.staff.credit':
                bills = self.env['tha.staff.credit'].browse([i for i in ids if i]).exists()
                bills.check_access('read')
                if 'bill_ids' in names:
                    values['bill_ids'] = [Command.set(bills.ids)]
                if bills and len(bills.company_id) == 1:
                    values['company_id'] = bills.company_id.id
                    if len(bills) == 1 and self.env.context.get('tha_from_credit_form'):
                        bill = bills
                        if 'employee_id' in names:
                            values['employee_id'] = bill.employee_id.id
                        if 'department_id' in names:
                            values['department_id'] = bill.department_id.id
                        if 'category' in names:
                            values['category'] = bill.category
        return values

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.department_id = self.employee_id.department_id
        else:
            self.department_id = False

    def _bills(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise AccessError(_('Select an allowed company.'))
        start = self.month.replace(day=1) if self.month else False
        domain = [('company_id', '=', self.company_id.id), ('state', '=', 'posted')]
        if self.date_from:
            domain.append(('charge_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('charge_date', '<=', self.date_to))
        if self.month:
            domain.append(('charge_date', '<=', fields.Date.end_of(start, 'month')))
        if self.mode == 'deductions':
            if not self.bill_ids:
                raise UserError(_('Open a staff credit bill or select bills in the list before generating deductions.'))
            self.bill_ids.check_access('read')
            if self.bill_ids.company_id != self.company_id:
                raise UserError(_('All selected staff credit bills must belong to the selected company.'))
            domain.append(('id', 'in', self.bill_ids.ids))
        if self.employee_id and self.mode == 'export':
            domain.append(('employee_id', '=', self.employee_id.id))
        if self.mode == 'export':
            if self.bill_ids:
                self.bill_ids.check_access('read')
                if self.bill_ids.company_id != self.company_id:
                    raise UserError(_('Select staff credit bills from one company at a time.'))
                domain.append(('id', 'in', self.bill_ids.ids))
            if self.department_id:
                domain.append(('department_id', '=', self.department_id.id))
            if self.category:
                domain.append(('category', '=', self.category))
        return self.env['tha.staff.credit'].search(domain, order='department_id, employee_id, charge_date, id')

    def _rows(self):
        self.ensure_one()
        end = fields.Date.end_of(self.month.replace(day=1), 'month') if self.month else fields.Date.context_today(self)
        start = self.month.replace(day=1) if self.month else end.replace(day=1)
        rows = []
        for bill in self._bills():
            settled = bill._settled_at(end)
            balance = bill.amount - settled
            zero = bill.currency_id.is_zero(balance)
            if (self.status == 'open' and zero) or (self.status == 'settled' and not zero):
                continue
            plan = bill.schedule_ids.sorted(lambda s: (s.due_date, s.id))
            current = plan.filtered(lambda s: start <= s.due_date <= end)
            amounts = plan.mapped('amount')
            if not amounts:
                installment = bill.currency_id.round(bill.amount / bill.installment_count)
                amounts = [installment] * (bill.installment_count - 1)
                amounts.append(bill.amount - sum(amounts))
            # Manual settlements have no installment link: cover the oldest amounts first.
            completed, covered = 0, 0
            for amount in amounts:
                if bill.currency_id.compare_amounts(settled, 0) <= 0:
                    break
                covered += amount
                if bill.currency_id.compare_amounts(settled, covered) < 0:
                    break
                completed += 1
            times = '%s/%s' % (completed, len(amounts))
            rows.append([len(rows) + 1, bill.charge_date, bill.employee_id.name, bill.department_id.name,
                         bill.description, bill.amount, settled, times, sum(current.mapped('amount')), balance,
                         bill.remark or '', bill.name, bill.anzer_reference or '', bill.source_move_id.name])
        return rows

    def _xlsx(self):
        self.ensure_one()
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
        book.formats[0].set_font_name('Calibri')
        book.formats[0].set_font_size(11)
        title = book.add_format({'bold': True, 'font_size': 18, 'font_color': '#FFFFFF',
                                 'bg_color': '#17365D', 'valign': 'vcenter'})
        header = book.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#24476B', 'border': 1, 'border_color': '#D7E1EB', 'text_wrap': True, 'align': 'center', 'valign': 'vcenter'})
        subheader = book.add_format({'bold': True, 'bg_color': '#D9E2F3', 'border': 1, 'text_wrap': True, 'align': 'center', 'valign': 'vcenter'})
        text = book.add_format({'font_color': '#34465A', 'text_wrap': True, 'valign': 'vcenter'})
        total_label = book.add_format({'bold': True, 'bg_color': '#E2F0D9', 'border': 1})
        total_money = book.add_format({'bold': True, 'bg_color': '#E2F0D9', 'border': 1, 'num_format': '#,##0.00;[Red](#,##0.00);-'})
        sheet = book.add_worksheet('Staff Credit Report')
        label = self.month.strftime("%b'%y") if self.month else 'All months'
        cutoff = fields.Date.end_of(self.month, 'month') if self.month else fields.Date.context_today(self)
        sheet.merge_range(0, 0, 0, 13, '%s | Staff Credit Report | %s' % (self.company_id.name, label), title)
        sheet.merge_range(1, 0, 1, 13, 'Currency: %s  |  Report date: %s' % (
            self.company_id.currency_id.name, fields.Date.context_today(self).strftime('%d %b %Y')), text)
        scope = 'Selected bills (%s)' % len(self.bill_ids) if self.bill_ids else 'Company records'
        filters = [scope, 'Status: %s' % dict(self._fields['status'].selection)[self.status]]
        for caption, value in [('Employee', self.employee_id.name), ('Department', self.department_id.name),
                               ('Category', dict(CATEGORIES).get(self.category)),
                               ('From', self.date_from), ('To', self.date_to)]:
            if value:
                filters.append('%s: %s' % (caption, value))
        sheet.merge_range(2, 0, 2, 13, '  |  '.join(filters), text)
        # Two header rows mirror the supplied workbook: grouped settlement/month columns
        # sit above concise subheadings used for the actual data columns.
        for col, value in enumerate(['No', 'Date', 'Staff name', 'Department', 'Name (Patient & Others)', '100% Bill']):
            sheet.merge_range(3, col, 4, col, value, header)
        sheet.merge_range(3, 6, 3, 8, 'Settlement', header)
        plan_label = self.month.strftime("%b'%y") if self.month else cutoff.strftime("%b'%y")
        sheet.write(4, 8, plan_label + '\nPlanned amount', subheader)
        sheet.merge_range(3, 9, 4, 9, 'Balance\nas at ' + cutoff.strftime('%d %b %Y'), header)
        for col, value in ((10, 'Remark'), (11, 'System Reference'), (12, 'Anzer System invoice'), (13, 'Odoo System invoice')):
            sheet.merge_range(3, col, 4, col, value, header)
        sheet.write(4, 6, 'Posted through\n' + cutoff.strftime('%d %b %Y'), subheader)
        sheet.write(4, 7, 'Times', subheader)
        rows = self._rows()
        widths = [6, 15, 23, 23, 43, 18, 18, 10, 18, 18, 48, 21, 23, 25]
        formats = {}
        for stripe, color in enumerate(('#FFFFFF', '#F2F6FA')):
            base = {'bg_color': color, 'font_color': '#243746', 'bottom': 1,
                    'bottom_color': '#D7E1EB', 'text_wrap': True, 'valign': 'top'}
            for kind, extra in [('text', {}), ('date', {'num_format': 'dd-mmm-yyyy'}),
                                ('money', {'num_format': '#,##0.00;[Red](#,##0.00);–', 'align': 'right'}),
                                ('center', {'align': 'center'})]:
                formats[stripe, kind] = book.add_format(dict(base, **extra))
        for number, row in enumerate(rows, 5):
            for col, value in enumerate(row):
                kind = 'money' if col in (5, 6, 8, 9) else 'date' if col == 1 else 'center' if col in (0, 7) else 'text'
                sheet.write(number, col, value, formats[(number - 5) % 2, kind])
            # Size wrapped narrative rows, including explicit newlines, so notes remain readable.
            line_count = max(sum(max(1, len(textwrap.wrap(part, max(1, int(widths[col]) - 2))))
                                 for part in str(row[col] or '').split('\n')) for col in (2, 3, 4, 10, 11, 12, 13))
            sheet.set_row(number, min(409, max(34, math.ceil(line_count * 15 + 10))))
        total = 5 + len(rows)
        sheet.write(total, 0, 'Total', total_label)
        for col in (1, 2, 3, 4, 7, 10, 11, 12, 13):
            sheet.write_blank(total, col, None, total_label)
        for col in (5, 6, 8, 9):
            sheet.write_number(total, col, sum(row[col] for row in rows), total_money)
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        sheet.set_row(0, 38)
        sheet.set_row(1, 28)
        sheet.set_row(2, 25)
        sheet.set_row(3, 28)
        sheet.set_row(4, 38)
        sheet.set_row(total, 28)
        sheet.hide_gridlines(2)
        sheet.set_zoom(85)
        if rows:
            sheet.conditional_format(5, 9, total - 1, 9, {'type': 'cell', 'criteria': '>', 'value': 0,
                'format': book.add_format({'font_color': '#9C5700', 'bg_color': '#FFF2CC', 'bold': True})})
            sheet.conditional_format(5, 9, total - 1, 9, {'type': 'cell', 'criteria': '==', 'value': 0,
                'format': book.add_format({'font_color': '#276343', 'bg_color': '#E2F0D9'})})
        sheet.freeze_panes(5, 4)
        sheet.autofilter(4, 0, max(4, total - 1), 13)
        sheet.set_landscape()
        sheet.set_paper(8)
        sheet.set_margins(0.25, 0.25, 0.4, 0.4)
        sheet.set_footer('&LStaff Credit Report&CPage &P of &N&R' + self.company_id.currency_id.name)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, 4)
        sheet.print_area(0, 0, total, 13)
        book.close()
        return output.getvalue()

    def action_export(self):
        self.ensure_one()
        self.write({'file_data': base64.b64encode(self._xlsx()),
                    'filename': 'staff_credit_%s.xlsx' % (self.month.strftime('%Y_%m') if self.month else 'all_months')})
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%s/%s/file_data/%s?download=true' %
                (self._name, self.id, self.filename), 'target': 'download'}

    def action_generate(self):
        self.ensure_one()
        if (not self.env.user.has_group('tha_vhg_staff_credit_report.group_manager')
                or not self.env.user.has_group('account.group_account_user')):
            raise AccessError(_('Monthly deduction generation requires Staff Credit Manager and Accounting access.'))
        self.mode = 'deductions'
        bills = self._bills()
        config = self.env['tha.staff.credit.config'].search([('company_id', '=', self.company_id.id)], limit=1)
        override = (self.env.context.get('tha_staff_credit_account_id'),
                    self.env.context.get('tha_staff_credit_salary_account_id'),
                    self.env.context.get('tha_staff_credit_journal_id'))
        if all(override):
            config_values = {'account_id': override[0], 'salary_account_id': override[1], 'journal_id': override[2]}
            config = self.env['tha.staff.credit.config'].new(dict(config_values, company_id=self.company_id.id))
            config._check_settings()
        elif not config:
            raise UserError(_('Configure Staff Credit Settings first.'))
        if config.id:
            config._serialize()
        start = self.month.replace(day=1)
        moves = self.env['account.move']
        batches = self.env['tha.staff.credit.batch']
        schedules = self.env['tha.staff.credit.schedule'].search([
            ('credit_id', 'in', bills.ids), ('month', '=', start)], order='credit_id, id')
        for employee in schedules.credit_id.employee_id:
            batch = batches.search([('company_id', '=', self.company_id.id), ('employee_id', '=', employee.id),
                                    ('month', '=', start)], limit=1)
            selected = schedules.filtered(lambda s: s.credit_id.employee_id == employee)
            move = batch.move_id
            missing = selected - batch.schedule_ids if move else selected
            if move and not missing:
                moves |= move
                continue
            if move and move.state != 'draft':
                raise UserError(_('This staff member already has a posted or cancelled deduction for this month. New bills cannot be added; review the existing entry.'))
            if missing.deduction_line_ids:
                raise UserError(_('Some selected installments already have deduction links. Review the existing entries.'))
            for bill in selected.credit_id:
                if bill.currency_id.compare_amounts(sum(bill.schedule_ids.mapped('amount')), bill.amount) != 0:
                    raise UserError(_('The repayment plan for %s must total its original bill.', bill.name))
                if len(bill.schedule_ids) != bill.installment_count:
                    raise UserError(_('The installment count for %s differs from its plan.', bill.name))
            if not batch:
                batch = batches.create({'company_id': self.company_id.id, 'employee_id': employee.id, 'month': start})
            commands = [Command.create({
                'name': '%s - %s' % (s.credit_id.name, s.credit_id.description),
                'account_id': s.credit_id.source_line_id.account_id.id,
                'partner_id': s.credit_id.partner_id.id, 'credit': s.amount,
                'date_maturity': fields.Date.end_of(start, 'month'),
                'tha_staff_credit_id': s.credit_id.id, 'tha_staff_credit_schedule_id': s.id,
            }) for s in missing]
            if move:
                salary = move.line_ids.filtered(lambda l: not l.tha_staff_credit_id)
                if len(salary) != 1 or salary.account_id != config.salary_account_id or move.journal_id != config.journal_id:
                    raise UserError(_('The existing draft no longer matches Settings. Delete it and generate again.'))
                total = sum(move.line_ids.filtered('tha_staff_credit_id').mapped('credit')) + sum(missing.mapped('amount'))
                move.write({'line_ids': [Command.update(salary.id, {'debit': total})] + commands})
                batch.schedule_ids = batch.schedule_ids | missing
            else:
                total = sum(selected.mapped('amount'))
                move = self.env['account.move'].create({
                    'company_id': self.company_id.id, 'journal_id': config.journal_id.id,
                    'date': fields.Date.end_of(start, 'month'), 'tha_staff_credit_batch_id': batch.id,
                    'ref': 'Staff Credit - %s - %s' % (employee.name, start.strftime('%Y-%m')),
                    'line_ids': [Command.create({'name': 'Staff Credit salary deduction - %s' % employee.name,
                                                 'account_id': config.salary_account_id.id, 'debit': total})] + commands,
                })
                batch.write({'move_id': move.id, 'schedule_ids': [Command.set(selected.ids)]})
            selected.credit_id._check_capacity()
            for bill in selected.credit_id:
                bill.message_post(body=_('Created monthly deduction draft: %s', move.ref))
            moves |= move
        if not moves:
            raise UserError(_('No installments are scheduled for this company/staff and month.'))
        return {'type': 'ir.actions.act_window', 'name': _('Staff Credit Monthly Deductions'),
                'res_model': 'account.move', 'view_mode': 'list,form', 'domain': [('id', 'in', moves.ids)],
                'context': {'create': False}}


class CreditSettingsWizard(models.TransientModel):
    _name = 'tha.staff.credit.settings.wizard'
    _description = 'Staff Credit Settings Override'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True)
    credit_id = fields.Many2one('tha.staff.credit', required=True, readonly=True, check_company=True)
    account_id = fields.Many2one('account.account', required=True, check_company=True, string='Staff Credit account')
    salary_account_id = fields.Many2one('account.account', required=True, check_company=True,
                                        string='Salary expense / Cash-Bank clearing account')
    invoice_credit_account_id = fields.Many2one('account.account', check_company=True,
                                                string='Original invoice credit account')
    journal_id = fields.Many2one('account.journal', required=True, check_company=True, string='Deduction journal')
    save_as_default = fields.Boolean(string='Save as company default', default=False)

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        company = self.env['res.company'].browse(values.get('company_id', self.env.company.id))
        config = self.env['tha.staff.credit.config'].search([('company_id', '=', company.id)], limit=1)
        for field, config_field, code in (
                ('account_id', 'account_id', '130100'), ('salary_account_id', 'salary_account_id', '701010')):
            if field in names and not values.get(field):
                values[field] = (getattr(config, config_field).id if config else self.env['account.account'].search([
                    ('company_ids', 'in', company.id), ('code', '=', code)], limit=1).id)
        if 'invoice_credit_account_id' in names and not values.get('invoice_credit_account_id'):
            values['invoice_credit_account_id'] = (config.invoice_credit_account_id.id if config else
                self.env['account.account'].with_company(company).search([
                    ('company_ids', 'in', company.id), ('code', '=', '510585')], limit=1).id)
        if 'journal_id' in names and not values.get('journal_id') and config:
            values['journal_id'] = config.journal_id.id
        return values

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('tha_vhg_staff_credit_report.group_manager'):
            raise AccessError(_('Only Staff Credit managers may configure settings.'))
        if self.save_as_default:
            config = self.env['tha.staff.credit.config'].search([('company_id', '=', self.company_id.id)], limit=1)
            values = {'account_id': self.account_id.id, 'salary_account_id': self.salary_account_id.id,
                      'journal_id': self.journal_id.id,
                      'invoice_credit_account_id': self.invoice_credit_account_id.id}
            if config:
                config.write(values)
            else:
                self.env['tha.staff.credit.config'].create(dict(values, company_id=self.company_id.id))
        return {'type': 'ir.actions.act_window', 'name': _('Staff Credit Bill'),
                'res_model': 'tha.staff.credit', 'res_id': self.credit_id.id,
                'view_mode': 'form', 'target': 'current',
                'context': {'tha_staff_credit_account_id': self.account_id.id,
                            'tha_staff_credit_salary_account_id': self.salary_account_id.id,
                            'tha_staff_credit_journal_id': self.journal_id.id,
                            'tha_staff_credit_invoice_credit_account_id': self.invoice_credit_account_id.id}}
