from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

CATEGORIES = [('hospital', 'Hospital bill'), ('damage', 'Damage'), ('penalty', 'Penalty'),
              ('meals', 'Meals'), ('other', 'Other')]


class CreditConfig(models.Model):
    _name = 'tha.staff.credit.config'
    _description = 'Staff Credit Settings'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    account_id = fields.Many2one('account.account', required=True, check_company=True, string='Staff Credit account')
    salary_account_id = fields.Many2one('account.account', required=True, check_company=True, string='Salary expense account')
    journal_id = fields.Many2one('account.journal', required=True, check_company=True,
                                 domain="[('company_id', '=', company_id), ('type', '=', 'general')]")
    revision = fields.Integer(default=0, readonly=True)
    _company_unique = models.Constraint('UNIQUE(company_id)', 'Configure each company only once.')

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        company = self.env['res.company'].browse(values.get('company_id', self.env.company.id))
        for field, code in (('account_id', '130100'), ('salary_account_id', '701010')):
            if field in names:
                values[field] = self.env['account.account'].search([
                    ('company_ids', 'in', company.id), ('code', '=', code)], limit=1).id
        return values

    @api.constrains('company_id', 'account_id', 'salary_account_id', 'journal_id')
    def _check_settings(self):
        for config in self:
            if (config.company_id not in config.account_id.company_ids
                    or config.account_id.account_type != 'asset_receivable' or not config.account_id.reconcile
                    or config.company_id not in config.salary_account_id.company_ids
                    or config.salary_account_id.account_type not in ('expense', 'expense_direct_cost')
                    or config.journal_id.company_id != config.company_id or config.journal_id.type != 'general'
                    or not config.account_id.active or not config.salary_account_id.active
                    or (config.journal_id.currency_id and config.journal_id.currency_id != config.company_id.currency_id)):
                raise ValidationError(_('Select an active reconcilable receivable, salary expense account and general journal in this company.'))
            if self.env['tha.staff.credit'].search_count([
                    ('company_id', '=', config.company_id.id), ('source_line_id.account_id', '!=', config.account_id.id)]):
                raise ValidationError(_('Existing bill links use another Staff Credit account.'))

    def _serialize(self):
        # An ORM write serializes competing allocations and causes stale
        # repeatable-read snapshots to retry before they can double allocate.
        for config in self.sorted('id'):
            config.write({'revision': config.revision + 1})

    def write(self, values):
        if 'company_id' in values and any(c.company_id.id != values['company_id'] for c in self):
            raise UserError(_('Create separate settings for another company.'))
        return super().write(values)

    def unlink(self):
        if self.env['tha.staff.credit'].search_count([('company_id', 'in', self.company_id.ids)]):
            raise UserError(_('Settings are required by existing staff bills.'))
        return super().unlink()


class StaffCredit(models.Model):
    _name = 'tha.staff.credit'
    _description = 'Staff Credit Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'charge_date, id'
    _check_company_auto = True

    name = fields.Char(default='New', required=True, copy=False, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee.public', required=True, check_company=True, tracking=True)
    department_id = fields.Many2one('hr.department', required=True, check_company=True, tracking=True)
    partner_id = fields.Many2one('res.partner', required=True, check_company=True, tracking=True)
    source_move_id = fields.Many2one('account.move', required=True, check_company=True, ondelete='restrict',
                                    string='Original invoice / entry', tracking=True,
                                    domain="[('company_id', '=', company_id), ('state', '=', 'posted')]")
    source_line_id = fields.Many2one('account.move.line', required=True, check_company=True, ondelete='restrict',
                                    string='Staff Credit debit item', tracking=True,
                                    domain="[('move_id', '=', source_move_id), ('debit', '>', 0)]")
    source_line_selection_required = fields.Boolean(
        compute='_compute_source_line_selection_required', compute_sudo=True)
    charge_date = fields.Date(required=True, tracking=True)
    description = fields.Char(required=True, tracking=True, string='Patient / other description')
    category = fields.Selection(CATEGORIES, default='hospital', required=True)
    amount = fields.Monetary(required=True, tracking=True, string='100% Bill')
    anzer_reference = fields.Char(tracking=True, string='Anzer System invoice')
    remark = fields.Text(tracking=True)
    start_month = fields.Date(required=True, tracking=True, string='Repayment from')
    end_date = fields.Date(compute='_compute_end_date', string='Repayment to')
    installment_count = fields.Integer(default=3, required=True, tracking=True)
    authorizer_id = fields.Many2one('res.users', string='Authorized by', tracking=True)
    authorization_date = fields.Date(tracking=True)
    schedule_ids = fields.One2many('tha.staff.credit.schedule', 'credit_id', copy=False)
    allocation_ids = fields.One2many('tha.staff.credit.allocation', 'credit_id', copy=False)
    deduction_line_ids = fields.One2many('account.move.line', 'tha_staff_credit_id', readonly=True)
    settled_amount = fields.Monetary(compute='_compute_balance')
    balance = fields.Monetary(compute='_compute_balance')

    @api.depends('start_month', 'installment_count', 'schedule_ids.due_date')
    def _compute_end_date(self):
        for bill in self:
            bill.end_date = max(bill.schedule_ids.mapped('due_date'), default=False) or (
                bill.start_month + relativedelta(months=max(0, bill.installment_count - 1), day=31)
                if bill.start_month else False)

    @api.depends('amount', 'allocation_ids.amount', 'allocation_ids.source_line_id.parent_state',
                 'deduction_line_ids.balance', 'deduction_line_ids.parent_state')
    def _compute_balance(self):
        for bill in self:
            bill.settled_amount = bill._settled_at()
            bill.balance = bill.amount - bill.settled_amount

    def _settled_at(self, cutoff=None):
        self.ensure_one()
        manual = self.allocation_ids.filtered(lambda a: a.source_line_id.parent_state == 'posted'
                                               and (not cutoff or a.date <= cutoff))
        generated = self.deduction_line_ids.filtered(lambda l: l.parent_state == 'posted'
                                                     and (not cutoff or l.date <= cutoff))
        return sum(manual.mapped('amount')) - sum(generated.mapped('balance'))

    def _config(self):
        self.ensure_one()
        config = self.env['tha.staff.credit.config'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not config:
            raise UserError(_('Open Settings and configure this company first.'))
        return config

    @api.depends('source_move_id', 'source_move_id.line_ids.account_id',
                 'source_move_id.line_ids.debit', 'company_id')
    def _compute_source_line_selection_required(self):
        for bill in self:
            config = self.env['tha.staff.credit.config'].search([
                ('company_id', '=', bill.company_id.id)], limit=1)
            lines = bill.source_move_id.line_ids.filtered(
                lambda line: line.account_id == config.account_id and line.debit > 0)
            bill.source_line_selection_required = bool(bill.source_move_id) and len(lines) != 1

    @api.onchange('employee_id')
    def _onchange_employee(self):
        if self.employee_id:
            self.department_id = self.employee_id.department_id
            self.partner_id = self.employee_id.work_contact_id

    @api.onchange('source_move_id')
    def _onchange_move(self):
        self.source_line_id = False
        if self.source_move_id:
            config = self._config()
            lines = self.source_move_id.line_ids.filtered(lambda l: l.account_id == config.account_id and l.debit > 0)
            if len(lines) == 1:
                self.source_line_id = lines
                self._onchange_source()

    @api.onchange('source_line_id')
    def _onchange_source(self):
        if self.source_line_id:
            line = self.source_line_id
            self.source_move_id = line.move_id
            self.charge_date = line.date
            self.partner_id = line.partner_id
            self.amount = line.debit
            self.description = line.name or line.move_id.ref or line.move_id.name
            self.start_month = line.date.replace(day=1)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for bill in records:
            # The company settings lock also serializes first-time sequence creation.
            bill._config()._serialize()
            sequences = self.env['ir.sequence'].sudo().with_company(bill.company_id)
            sequence = sequences.search([('code', '=', 'tha.staff.credit'),
                                         ('company_id', '=', bill.company_id.id)], limit=1)
            if not sequence:
                prefix = 'SC/%s/' % bill.company_id.id
                existing = self.sudo().search([('company_id', '=', bill.company_id.id),
                                               ('name', '=like', prefix + '%')]).mapped('name')
                last = max((int(name[len(prefix):]) for name in existing
                            if name[len(prefix):].isdigit()), default=0)
                sequence = sequences.create({'name': 'Staff Credit - %s' % bill.company_id.name,
                    'code': 'tha.staff.credit', 'company_id': bill.company_id.id,
                    'prefix': prefix, 'padding': 6, 'number_next': last + 1})
            bill.name = sequence.next_by_id()
        return records

    @api.constrains('source_move_id', 'source_line_id', 'amount', 'company_id', 'partner_id',
                    'employee_id', 'department_id', 'charge_date', 'start_month', 'installment_count')
    def _check_bill(self):
        for bill in self:
            config = bill._config()
            config._serialize()
            line = bill.source_line_id
            if (line.move_id != bill.source_move_id or line.parent_state != 'posted' or line.debit <= 0
                    or line.account_id != config.account_id or line.company_id != bill.company_id
                    or line.currency_id != bill.currency_id or line.partner_id != bill.partner_id
                    or bill.charge_date != line.date or bill.employee_id.company_id != bill.company_id
                    or (bill.department_id.company_id and bill.department_id.company_id != bill.company_id)):
                raise ValidationError(_('Link a posted company-currency Staff Credit debit matching company, partner and date. Staff and department must belong to the company.'))
            if (bill.amount <= 0 or not 1 <= bill.installment_count <= 600
                    or bill.start_month.replace(day=1) < bill.charge_date.replace(day=1)):
                raise ValidationError(_('Use a positive bill, 1-600 installments, and a repayment start no earlier than the bill month.'))
            total = sum(self.search([('source_line_id', '=', line.id)]).mapped('amount'))
            if bill.currency_id.compare_amounts(total, line.debit) > 0:
                raise ValidationError(_('Bill links exceed the original debit amount.'))

    def _check_capacity(self):
        for bill in self:
            reserved = -sum(bill.deduction_line_ids.filtered(
                lambda l: l.parent_state == 'draft' and not l.move_id.reversed_entry_id).mapped('balance'))
            if bill.currency_id.compare_amounts(bill._settled_at() + reserved, bill.amount) > 0:
                raise ValidationError(_('Posted settlements and reserved draft deductions exceed the bill amount.'))

    def write(self, values):
        identity = {'source_move_id', 'source_line_id', 'amount', 'company_id', 'partner_id', 'employee_id', 'charge_date'}
        if identity & values.keys() and any(b.schedule_ids or b.allocation_ids or b.deduction_line_ids for b in self):
            raise UserError(_('Remove unused schedules and settlement links before changing the bill identity or amount.'))
        return super().write(values)

    def unlink(self):
        if any(b.allocation_ids or b.deduction_line_ids for b in self):
            raise UserError(_('A bill with settlement or deduction links cannot be deleted.'))
        return super().unlink()

    def action_generate_schedule(self):
        self.ensure_one()
        if self.allocation_ids or self.deduction_line_ids:
            raise UserError(_('The schedule cannot be replaced after settlements or deductions are linked.'))
        amount = self.currency_id.round(self.amount / self.installment_count)
        final = self.currency_id.round(self.amount - amount * (self.installment_count - 1))
        if min(amount, final) <= 0:
            raise UserError(_('Too many installments for the currency rounding.'))
        self.schedule_ids.unlink()
        self.write({'schedule_ids': [Command.create({
            'due_date': self.start_month.replace(day=1) + relativedelta(months=i, day=31),
            'amount': final if i == self.installment_count - 1 else amount,
        }) for i in range(self.installment_count)]})
        self.message_post(body=_('Generated monthly repayment plan.'))

    def action_settings(self):
        if not self.env.user.has_group('tha_vhg_staff_credit_report.group_manager'):
            raise AccessError(_('Only Staff Credit managers may configure settings.'))
        self.ensure_one()
        config = self.env['tha.staff.credit.config'].search([('company_id', '=', self.company_id.id)], limit=1)
        return {'type': 'ir.actions.act_window', 'name': _('Staff Credit Settings'),
                'res_model': 'tha.staff.credit.settings.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_company_id': self.company_id.id, 'default_credit_id': self.id,
                            'default_account_id': config.account_id.id if config else False,
                            'default_salary_account_id': config.salary_account_id.id if config else False,
                            'default_journal_id': config.journal_id.id if config else False,
                            'default_save_as_default': False}}


class CreditSchedule(models.Model):
    _name = 'tha.staff.credit.schedule'
    _description = 'Staff Credit Installment'
    _order = 'due_date, id'
    _check_company_auto = True

    credit_id = fields.Many2one('tha.staff.credit', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='credit_id.company_id', store=True)
    currency_id = fields.Many2one(related='credit_id.currency_id')
    due_date = fields.Date(required=True)
    month = fields.Date(compute='_compute_month', store=True)
    amount = fields.Monetary(required=True)
    deduction_line_ids = fields.One2many('account.move.line', 'tha_staff_credit_schedule_id', readonly=True)
    locked = fields.Boolean(compute='_compute_locked')
    _month_unique = models.Constraint('UNIQUE(credit_id, month)', 'Use one installment per bill per month.')

    @api.depends('due_date')
    def _compute_month(self):
        for line in self:
            line.month = line.due_date.replace(day=1) if line.due_date else False

    @api.depends('deduction_line_ids')
    def _compute_locked(self):
        for line in self:
            line.locked = bool(line.deduction_line_ids)

    @api.constrains('amount', 'due_date', 'credit_id')
    def _check_schedule(self):
        for line in self:
            if line.amount <= 0 or line.due_date < line.credit_id.charge_date:
                raise ValidationError(_('Installments need a positive amount and a date on or after the bill.'))

    def write(self, values):
        if {'amount', 'due_date', 'credit_id'} & values.keys() and any(self.mapped('locked')):
            raise UserError(_('Delete the unposted deduction draft before editing its installment. Posted deductions require reversal.'))
        if 'credit_id' in values:
            raise UserError(_('Installments cannot move between bills.'))
        return super().write(values)

    def unlink(self):
        if any(self.mapped('locked')):
            raise UserError(_('An installment linked to a deduction cannot be deleted.'))
        return super().unlink()


class CreditAllocation(models.Model):
    _name = 'tha.staff.credit.allocation'
    _description = 'Existing Staff Credit Settlement'
    _order = 'id'
    _check_company_auto = True

    credit_id = fields.Many2one('tha.staff.credit', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='credit_id.company_id', store=True)
    currency_id = fields.Many2one(related='credit_id.currency_id')
    source_line_id = fields.Many2one('account.move.line', required=True, ondelete='restrict', check_company=True,
                                    domain="[('company_id', '=', company_id), ('parent_state', '=', 'posted'), ('credit', '>', 0), ('tha_staff_credit_id', '=', False)]")
    move_id = fields.Many2one(related='source_line_id.move_id')
    date = fields.Date(related='source_line_id.date')
    amount = fields.Monetary(required=True)
    kind = fields.Selection([('repayment', 'Repayment'), ('adjustment', 'Adjustment')], default='repayment', required=True)
    _source_unique = models.Constraint('UNIQUE(credit_id, source_line_id)', 'This settlement is already linked to the bill.')

    @api.constrains('credit_id', 'source_line_id', 'amount')
    def _check_allocation(self):
        for allocation in self:
            bill, line = allocation.credit_id, allocation.source_line_id
            bill._config()._serialize()
            if (line.parent_state != 'posted' or line.credit <= 0 or line.tha_staff_credit_id
                    or line.company_id != bill.company_id or line.account_id != bill.source_line_id.account_id
                    or line.currency_id != bill.currency_id or line.partner_id != bill.partner_id
                    or line.date < bill.charge_date or allocation.amount <= 0):
                raise ValidationError(_('Select an existing posted credit matching bill account, partner and currency, dated on or after the bill. Generated deductions count automatically.'))
            total = sum(self.search([('source_line_id', '=', line.id)]).mapped('amount'))
            if bill.currency_id.compare_amounts(total, line.credit) > 0:
                raise ValidationError(_('Allocations exceed the existing credit amount.'))
            bill._check_capacity()

    def write(self, values):
        if {'credit_id', 'source_line_id'} & values.keys():
            raise UserError(_('Remove and recreate a settlement link to change its source.'))
        return super().write(values)


class CreditBatch(models.Model):
    _name = 'tha.staff.credit.batch'
    _description = 'Monthly Staff Credit Deduction'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True)
    employee_id = fields.Many2one('hr.employee.public', required=True, check_company=True)
    month = fields.Date(required=True)
    move_id = fields.Many2one('account.move', check_company=True, ondelete='set null', readonly=True)
    schedule_ids = fields.Many2many('tha.staff.credit.schedule', check_company=True, readonly=True)
    _staff_month_unique = models.Constraint('UNIQUE(company_id, employee_id, month)', 'A monthly deduction already exists for this staff member.')
