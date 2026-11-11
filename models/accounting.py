from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    tha_staff_credit_batch_id = fields.Many2one('tha.staff.credit.batch', copy=False, ondelete='restrict',
                                               check_company=True, readonly=True)
    tha_staff_credit_id = fields.Many2one('tha.staff.credit', copy=False, ondelete='restrict',
                                          check_company=True, readonly=True,
                                          string='Pending Staff Credit bill')

    def tha_check_source_links(self):
        if (self.env['tha.staff.credit'].sudo().search_count([('source_move_id', 'in', self.ids)])
                or self.env['tha.staff.credit.allocation'].sudo().search_count([('move_id', 'in', self.ids)])):
            raise UserError(_('Remove the Staff Credit bill/settlement links before changing this accounting source.'))

    def write(self, values):
        if {'state', 'date', 'company_id', 'journal_id', 'partner_id'} & values.keys():
            changed = self.filtered(lambda m: any(
                key in values and values[key] != (m[key].id if hasattr(m[key], 'id') else m[key])
                for key in ('state', 'date', 'company_id', 'journal_id', 'partner_id')))
            changed.tha_check_source_links()
            generated = changed.filtered(lambda m: m.line_ids.tha_staff_credit_id and m.state == 'posted')
            if generated:
                raise UserError(_('Posted Staff Credit deductions must be corrected with a standard reversal.'))
        if ('tha_staff_credit_batch_id' in values
                or ('tha_staff_credit_id' in values and not self.env.context.get('tha_staff_credit_unlink'))):
            raise UserError(_('Staff Credit accounting links cannot be changed.'))
        result = super().write(values)
        if values.get('state') == 'cancel':
            pending = self.sudo().filtered(lambda m: m.tha_staff_credit_id and m.tha_staff_credit_id.state == 'draft')
            pending.mapped('tha_staff_credit_id').sudo().write({'state': 'cancel'})
        elif values.get('state') == 'draft':
            cancelled = self.sudo().filtered(lambda m: m.tha_staff_credit_id and m.tha_staff_credit_id.state == 'cancel')
            cancelled.mapped('tha_staff_credit_id').sudo().write({'state': 'draft'})
        return result

    def _reverse_moves(self, default_values_list=None, cancel=False):
        self.tha_check_source_links()
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def _post(self, soft=True):
        linked = self.filtered(lambda m: m.line_ids.tha_staff_credit_id or m.tha_staff_credit_batch_id)
        bills = linked.line_ids.tha_staff_credit_id
        configs = self.env['tha.staff.credit.config'].sudo().search([('company_id', 'in', linked.company_id.ids)])
        configs._serialize()
        for move in linked:
            tagged = move.line_ids.filtered('tha_staff_credit_id')
            if move.reversed_entry_id:
                original = move.reversed_entry_id
                expected = sorted((l.tha_staff_credit_id.id, l.tha_staff_credit_schedule_id.id,
                                   l.account_id.id, l.partner_id.id, l.currency_id.id, -l.balance)
                                  for l in original.line_ids)
                actual = sorted((l.tha_staff_credit_id.id, l.tha_staff_credit_schedule_id.id,
                                 l.account_id.id, l.partner_id.id, l.currency_id.id, l.balance) for l in move.line_ids)
                if (not original.line_ids.tha_staff_credit_id or actual != expected or original.state != 'posted'
                        or move.company_id != original.company_id or move.date < original.date):
                    raise ValidationError(_('A deduction reversal must retain the original bill links and reverse their exact amounts, on or after the original date.'))
                other = original.reversal_move_ids.filtered(lambda r: r != move and r.state == 'posted')
                if other:
                    raise ValidationError(_('This Staff Credit entry already has a posted reversal.'))
            else:
                batch = move.tha_staff_credit_batch_id
                config = configs.filtered(lambda c: c.company_id == move.company_id)
                if (not batch or batch.move_id != move or not tagged or not config
                        or move.company_id != batch.company_id or move.journal_id != config.journal_id
                        or move.date != fields.Date.end_of(batch.month, 'month')):
                    raise ValidationError(_('Generate deductions from Staff Credit; retain the configured journal and month-end date.'))
                seen = set()
                for line in tagged:
                    schedule, bill = line.tha_staff_credit_schedule_id, line.tha_staff_credit_id
                    if (not schedule or schedule.id in seen or schedule.credit_id != bill
                            or schedule.month != batch.month or bill.employee_id != batch.employee_id
                            or bill.company_id != batch.company_id or line.partner_id != bill.partner_id
                            or line.account_id != bill.source_line_id.account_id
                            or line.currency_id != bill.currency_id or line.debit
                            or bill.currency_id.compare_amounts(line.credit, schedule.amount)):
                        raise ValidationError(_('Deduction lines must match their bills and scheduled installments exactly.'))
                    seen.add(schedule.id)
                if seen != set(batch.schedule_ids.ids):
                    raise ValidationError(_('The draft must retain every selected installment in its batch. Delete the draft and generate it again.'))
                salary = move.line_ids - tagged
                if (len(salary) != 1 or salary.account_id != config.salary_account_id or salary.credit
                        or move.company_id.currency_id.compare_amounts(salary.debit, sum(tagged.mapped('credit')))):
                    raise ValidationError(_('The deduction must debit the configured salary account for the total bill credits.'))
        result = super()._post(soft=soft)
        for move in self.sudo().filtered(lambda m: m.tha_staff_credit_id and m.state == 'posted'):
            bill = move.tha_staff_credit_id
            if bill.state == 'posted':
                if bill.source_move_id != move:
                    raise ValidationError(_('This invoice is already linked to another Staff Credit bill.'))
                continue
            if bill.state != 'draft' or bill.invoice_id != move or move.move_type != 'out_invoice':
                raise ValidationError(_('Only the linked draft customer invoice can activate this Staff Credit bill.'))
            config = self.env['tha.staff.credit.config'].sudo().search([
                ('company_id', '=', bill.company_id.id)], limit=1)
            if not config or not config.invoice_credit_account_id:
                raise ValidationError(_('Configure the original invoice income account before posting this Staff Credit invoice.'))
            receivable = move.line_ids.filtered(lambda line: line.display_type == 'payment_term'
                and line.account_id == config.account_id and line.debit > 0)
            income = move.line_ids.filtered(lambda line: line.display_type == 'product' and line.credit > 0)
            if (not config or len(receivable) != 1 or move.company_id != bill.company_id
                    or move.partner_id != bill.partner_id or move.date != bill.charge_date
                    or move.currency_id != bill.currency_id
                    or bill.currency_id.compare_amounts(receivable.debit, bill.amount) != 0
                    or len(income) != 1 or income.account_id != config.invoice_credit_account_id
                    or bill.currency_id.compare_amounts(income.credit, bill.amount) != 0
                    or bill.currency_id.compare_amounts(move.amount_total, bill.amount) != 0
                    or move.amount_tax):
                raise ValidationError(_('The posted invoice must match the bill amount and use the configured Staff Credit receivable and income accounts without taxes.'))
            bill.sudo().write({'source_move_id': move.id, 'source_line_id': receivable.id, 'state': 'posted'})
            bill.sudo().message_post(body=_('Activated from posted original invoice: %s', move.name))
        bills._check_capacity()
        return result

    def unlink(self):
        self.tha_check_source_links()
        linked_bills = self.env['tha.staff.credit'].sudo().search([('invoice_id', 'in', self.ids)])
        if any(bill.invoice_id.state == 'posted' for bill in linked_bills):
            raise UserError(_('A posted Staff Credit invoice cannot be deleted.'))
        for bill in linked_bills:
            bill.write({'invoice_id': False, **({'state': 'draft'} if bill.state == 'cancel' else {})})
        self.sudo().with_context(tha_staff_credit_unlink=True).write({'tha_staff_credit_id': False})
        if any(m.state == 'posted' and m.line_ids.tha_staff_credit_id for m in self):
            raise UserError(_('Reverse posted Staff Credit deductions instead of deleting them.'))
        return super().unlink()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def tha_action_open_staff_credit_line(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Deduction Line'),
                'res_model': 'account.move.line', 'res_id': self.id,
                'views': [(False, 'form')], 'target': 'new',
                'context': {'form_view_initial_mode': 'readonly'}}

    # Copy the bill identity to standard reversal lines so historical reporting
    # subtracts the reversal only from its own accounting date onward.
    tha_staff_credit_id = fields.Many2one('tha.staff.credit', copy=True, ondelete='restrict', check_company=True)
    tha_staff_credit_schedule_id = fields.Many2one('tha.staff.credit.schedule', copy=True,
                                                  ondelete='restrict', check_company=True)

    @api.constrains('tha_staff_credit_id', 'tha_staff_credit_schedule_id', 'move_id')
    def tha_check_deduction_identity(self):
        for line in self:
            if not line.tha_staff_credit_id and not line.tha_staff_credit_schedule_id:
                continue
            bill, schedule, move = line.tha_staff_credit_id, line.tha_staff_credit_schedule_id, line.move_id
            if (not bill or not schedule or schedule.credit_id != bill
                    or move.company_id != bill.company_id
                    or (not move.tha_staff_credit_batch_id and not move.reversed_entry_id)):
                raise ValidationError(_('Bill and installment links belong only to generated deductions and their standard reversals.'))

    def tha_check_source_links(self):
        if (self.env['tha.staff.credit'].sudo().search_count([('source_line_id', 'in', self.ids)])
                or self.env['tha.staff.credit.allocation'].sudo().search_count([('source_line_id', 'in', self.ids)])):
            raise UserError(_('Remove Staff Credit source links before modifying these journal items.'))

    def write(self, values):
        protected = {'debit', 'credit', 'balance', 'amount_currency', 'currency_id', 'account_id',
                     'partner_id', 'date', 'company_id', 'move_id', 'tha_staff_credit_id',
                     'tha_staff_credit_schedule_id'}
        if protected & values.keys():
            self.tha_check_source_links()
            if any(l.tha_staff_credit_id and (l.move_id.state == 'posted' or l.move_id.tha_staff_credit_batch_id)
                   for l in self):
                raise UserError(_('Delete an unposted Staff Credit deduction and regenerate it; reverse posted deductions.'))
        return super().write(values)

    def unlink(self):
        self.tha_check_source_links()
        if any(l.tha_staff_credit_id and l.move_id.state == 'posted' for l in self):
            raise UserError(_('Posted Staff Credit lines require a reversal.'))
        return super().unlink()
