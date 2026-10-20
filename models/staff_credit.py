from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import ValidationError, UserError


CATEGORIES = [(key, label) for key, label in (
    ("hospital", "Hospital bill"), ("damage", "Damage"),
    ("penalty", "Penalty"), ("meals", "Meals"), ("other", "Other"),
)]


def lock_sources(env, lines):
    """Serialize company allocation checks, including repeatable-read transactions.

    Updating only configuration metadata ensures competing snapshots are retried;
    journal items and their accounting balances are never updated here.
    """
    if lines:
        configs = env["tha.staff.credit.config"].search([
            ("company_id", "in", lines.company_id.ids)], order="id")
        if configs:
            env.cr.execute("SELECT id FROM tha_staff_credit_config WHERE id IN %s ORDER BY id FOR UPDATE", [tuple(configs.ids)])
            configs.invalidate_recordset(["allocation_revision"])
            for config in configs:
                config.write({"allocation_revision": config.allocation_revision + 1})


class CreditConfig(models.Model):
    _name = "tha.staff.credit.config"
    _description = "Staff Credit Account Configuration"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    account_id = fields.Many2one("account.account", required=True, check_company=True,
                                domain="[('company_ids', 'in', company_id), ('account_type', '=', 'asset_receivable')]")
    currency_id = fields.Many2one(related="company_id.currency_id")
    allocation_revision = fields.Integer(readonly=True, copy=False)
    _company_unique = models.Constraint("UNIQUE(company_id)", "Configure one account per company.")

    @api.model
    def default_get(self, names):
        values = super().default_get(names)
        company = self.env["res.company"].browse(values.get("company_id", self.env.company.id))
        account = self.env["account.account"].with_company(company).search([
            ("company_ids", "in", company.id), ("code", "=", "130100"),
            ("account_type", "=", "asset_receivable"), ("reconcile", "=", True),
        ], limit=1)
        if "account_id" in names:
            values["account_id"] = account.id
        return values

    @api.constrains("account_id", "company_id")
    def _check_account(self):
        for record in self:
            if (record.company_id not in record.account_id.company_ids
                    or record.account_id.account_type != "asset_receivable" or not record.account_id.reconcile):
                raise ValidationError(_("Use a reconcilable receivable account belonging to this company."))
            credits = self.env["tha.staff.credit"].search([("company_id", "=", record.company_id.id)])
            if any(c.source_line_id.account_id != record.account_id for c in credits):
                raise ValidationError(_("The configured account cannot change while linked charges use another account."))

    def unlink(self):
        if self.env["tha.staff.credit"].search_count([("company_id", "in", self.company_id.ids)]):
            raise UserError(_("Configuration is required by existing staff credit records."))
        return super().unlink()

    def write(self, values):
        if "company_id" in values:
            changing = self.filtered(lambda c: c.company_id.id != values["company_id"])
            if self.env["tha.staff.credit"].search_count([("company_id", "in", changing.company_id.ids)]):
                raise UserError(_("Configuration cannot move to another company while charges exist."))
        return super().write(values)


class StaffCredit(models.Model):
    _name = "tha.staff.credit"
    _description = "Staff Credit Charge"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "charge_date, id"
    _check_company_auto = True

    name = fields.Char(required=True, default="New", copy=False, tracking=True)
    external_key = fields.Char(string="Import key", copy=False, index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    employee_id = fields.Many2one("hr.employee.public", required=True, check_company=True, tracking=True)
    partner_id = fields.Many2one("res.partner", required=True, check_company=True, tracking=True)
    department_id = fields.Many2one("hr.department", required=True, check_company=True, tracking=True)
    charge_date = fields.Date(required=True, tracking=True)
    category = fields.Selection(CATEGORIES, required=True, default="hospital", tracking=True)
    description = fields.Char(required=True, tracking=True)
    remark = fields.Text(tracking=True)
    source_line_id = fields.Many2one("account.move.line", required=True, check_company=True,
                                    ondelete="restrict", tracking=True,
                                    domain="[('company_id', '=', company_id), ('parent_state', '=', 'posted'), ('debit', '>', 0)]")
    source_move_id = fields.Many2one(related="source_line_id.move_id")
    amount = fields.Monetary(required=True, tracking=True)
    start_month = fields.Date(required=True, tracking=True)
    installment_count = fields.Integer(required=True, default=3, tracking=True)
    schedule_ids = fields.One2many("tha.staff.credit.schedule", "credit_id", copy=False)
    allocation_ids = fields.One2many("tha.staff.credit.allocation", "credit_id", copy=False)
    settled_amount = fields.Monetary(compute="_compute_balances")
    balance = fields.Monetary(compute="_compute_balances")
    warning = fields.Char(compute="_compute_balances")
    _external_unique = models.Constraint("UNIQUE(company_id, external_key)", "The import key already exists in this company.")

    @api.depends("amount", "allocation_ids.amount", "allocation_ids.source_line_id.parent_state", "schedule_ids.amount", "installment_count")
    def _compute_balances(self):
        for record in self:
            record.settled_amount = sum(record.allocation_ids.filtered(
                lambda a: a.source_line_id.parent_state == "posted").mapped("amount"))
            record.balance = record.amount - record.settled_amount
            warnings = []
            if not record.currency_id.is_zero(sum(record.schedule_ids.mapped("amount")) - record.amount):
                warnings.append(_("Schedule total differs from charge"))
            if len(record.schedule_ids) != record.installment_count:
                warnings.append(_("Schedule count differs from installment count"))
            record.warning = "; ".join(warnings)

    @api.onchange("employee_id")
    def _onchange_employee(self):
        if self.employee_id:
            self.department_id = self.employee_id.department_id
            # Public employee records deliberately avoid granting private HR access.
            self.partner_id = self.employee_id.work_contact_id

    @api.onchange("source_line_id")
    def _onchange_source(self):
        if self.source_line_id:
            self.charge_date = self.source_line_id.date
            self.start_month = self.source_line_id.date.replace(day=1)
            self.partner_id = self.source_line_id.partner_id
            self.amount = self.source_line_id.debit

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.name == "New":
                record.name = "SC/%s/%06d" % (record.company_id.id, record.id)
        return records

    @api.constrains("source_line_id", "amount", "company_id", "partner_id", "employee_id",
                    "department_id", "charge_date", "installment_count", "start_month")
    def _check_charge(self):
        lock_sources(self.env, self.source_line_id)
        for record in self:
            config = self.env["tha.staff.credit.config"].search([("company_id", "=", record.company_id.id)], limit=1)
            line = record.source_line_id
            if (not config or line.account_id != config.account_id or line.company_id != record.company_id
                    or line.parent_state != "posted" or line.debit <= 0):
                raise ValidationError(_("Link a posted debit on this company's configured staff-credit account."))
            if line.currency_id != record.currency_id:
                raise ValidationError(_("Version 1 supports journal items in company currency only."))
            if line.partner_id != record.partner_id:
                raise ValidationError(_("The accounting partner must match the source journal item."))
            if record.employee_id.company_id != record.company_id:
                raise ValidationError(_("Staff must belong to the selected company."))
            if record.charge_date != line.date:
                raise ValidationError(_("Charge date must match the posted journal-item date."))
            if record.amount <= 0 or record.installment_count < 1 or record.installment_count > 600:
                raise ValidationError(_("Use a positive charge and between 1 and 600 installments."))
            if record.start_month.replace(day=1) < record.charge_date.replace(day=1):
                raise ValidationError(_("Installments cannot start before the charge month."))
            allocated = sum(self.search([("source_line_id", "=", line.id)]).mapped("amount"))
            if record.currency_id.compare_amounts(allocated, line.debit) > 0:
                raise ValidationError(_("Charge allocations exceed the source debit."))
            if record.currency_id.compare_amounts(sum(record.allocation_ids.mapped("amount")), record.amount) > 0:
                raise ValidationError(_("Settlements exceed the charge."))

    def write(self, values):
        if {"amount", "source_line_id", "company_id", "partner_id", "employee_id", "charge_date"} & values.keys():
            if any(record.allocation_ids or record.schedule_ids for record in self):
                raise UserError(_("Remove the unsettled schedule and allocations before changing charge identity or amount."))
        return super().write(values)

    def unlink(self):
        if any(record.allocation_ids for record in self):
            raise UserError(_("Remove settlement allocations before deleting a charge."))
        return super().unlink()

    def action_generate_schedule(self):
        self.ensure_one()
        if self.allocation_ids:
            raise UserError(_("A schedule cannot be regenerated after settlements are assigned."))
        amount = self.currency_id.round(self.amount / self.installment_count)
        final = self.amount - amount * (self.installment_count - 1)
        if amount <= 0 or final <= 0:
            raise UserError(_("Too many installments for this charge and currency rounding."))
        self.schedule_ids.unlink()
        start = self.start_month.replace(day=1)
        self.write({"schedule_ids": [Command.create({
            "due_date": start + relativedelta(months=i, day=31),
            "amount": final if i == self.installment_count - 1 else amount,
        }) for i in range(self.installment_count)]})
        self.message_post(body=_("Generated monthly repayment schedule."))

    def paid_installments(self, cutoff):
        self.ensure_one()
        paid = sum(self.allocation_ids.filtered(lambda a: a.source_line_id.parent_state == "posted"
                    and a.source_line_id.date <= cutoff and a.kind == "repayment").mapped("amount"))
        count = 0
        for line in self.schedule_ids.sorted(lambda s: (s.due_date, s.id)):
            if self.currency_id.compare_amounts(paid, line.amount) < 0:
                break
            paid -= line.amount
            count += 1
        return count

    def action_suggest_settlements(self):
        self.ensure_one()
        if (self.search_count([("source_line_id", "=", self.source_line_id.id)]) != 1
                or self.currency_id.compare_amounts(self.amount, self.source_line_id.debit) != 0):
            raise UserError(_("This debit is split between charges. Allocate its settlements manually."))
        partials = self.source_line_id.matched_credit_ids.filtered(
            lambda p: p.credit_move_id.parent_state == "posted")
        candidates = {}
        for partial in partials:
            candidates[partial.credit_move_id.id] = candidates.get(partial.credit_move_id.id, 0) + partial.amount
        suggestions = []
        remaining = self.balance
        for line_id, amount in sorted(candidates.items()):
            source = self.env["account.move.line"].browse(line_id)
            existing = self.env["tha.staff.credit.allocation"].search([("source_line_id", "=", line_id)])
            if existing or amount > remaining or source.account_id != self.source_line_id.account_id:
                continue
            suggestions.append(Command.create({"source_line_id": line_id, "amount": amount}))
            remaining -= amount
        if not suggestions:
            raise UserError(_("No unambiguous, unallocated reconciled settlements were found."))
        wizard = self.env["tha.staff.credit.suggestion"].create({"credit_id": self.id, "line_ids": suggestions})
        return {"type": "ir.actions.act_window", "res_model": wizard._name, "res_id": wizard.id,
                "view_mode": "form", "target": "new"}


class CreditSchedule(models.Model):
    _name = "tha.staff.credit.schedule"
    _description = "Staff Credit Installment"
    _order = "due_date, id"
    _check_company_auto = True

    credit_id = fields.Many2one("tha.staff.credit", required=True, ondelete="cascade", check_company=True)
    company_id = fields.Many2one(related="credit_id.company_id", store=True)
    currency_id = fields.Many2one(related="credit_id.currency_id")
    due_date = fields.Date(required=True)
    amount = fields.Monetary(required=True)
    locked = fields.Boolean(compute="_compute_locked")

    def _compute_locked(self):
        for record in self:
            paid = record.credit_id.paid_installments(fields.Date.today())
            record.locked = record in record.credit_id.schedule_ids.sorted(lambda s: (s.due_date, s.id))[:paid]

    @api.constrains("amount", "due_date", "credit_id")
    def _check_schedule(self):
        for line in self:
            if line.amount <= 0 or line.due_date < line.credit_id.charge_date:
                raise ValidationError(_("Installments require a positive amount and a date on/after the charge."))
            others = line.credit_id.schedule_ids - line
            if any(s.due_date.replace(day=1) == line.due_date.replace(day=1) for s in others):
                raise ValidationError(_("Use one installment per month; move its date to skip a month."))

    def _check_editable(self):
        # Protect the paid prefix, including inserting/reordering rows before it.
        if any(c.allocation_ids for c in self.credit_id):
            for record in self:
                ordered = record.credit_id.schedule_ids.sorted(lambda s: (s.due_date, s.id))
                paid = record.credit_id.paid_installments(fields.Date.today())
                if record in ordered[:paid]:
                    raise UserError(_("Fully settled installments cannot be edited or removed."))

    def write(self, values):
        self._check_editable()
        if "credit_id" in values:
            raise UserError(_("Installments cannot be moved between charges."))
        self._check_paid_prefix(values.get("due_date"))
        result = super().write(values)
        self.credit_id.message_post(body=_("Edited an unpaid installment: %s", str(values)))
        return result

    def _check_paid_prefix(self, new_date):
        for credit in self.credit_id:
            paid = credit.paid_installments(fields.Date.today())
            ordered = credit.schedule_ids.sorted(lambda s: (s.due_date, s.id))
            if paid and new_date and fields.Date.to_date(new_date) <= ordered[paid - 1].due_date:
                raise UserError(_("An installment cannot be inserted before the paid schedule."))

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            credit = self.env["tha.staff.credit"].browse(values["credit_id"])
            credit.schedule_ids._check_paid_prefix(values.get("due_date"))
        result = super().create(vals_list)
        result.credit_id.message_post(body=_("Added repayment schedule lines.")) if len(result.credit_id) == 1 else None
        return result

    def unlink(self):
        self._check_editable()
        for credit in self.credit_id:
            credit.message_post(body=_("Removed unpaid installment(s)."))
        return super().unlink()


class CreditAllocation(models.Model):
    _name = "tha.staff.credit.allocation"
    _description = "Staff Credit Settlement Allocation"
    _order = "date, id"
    _check_company_auto = True

    credit_id = fields.Many2one("tha.staff.credit", required=True, ondelete="restrict", check_company=True)
    company_id = fields.Many2one(related="credit_id.company_id", store=True)
    currency_id = fields.Many2one(related="credit_id.currency_id")
    source_line_id = fields.Many2one("account.move.line", required=True, ondelete="restrict", check_company=True,
                                    domain="[('company_id', '=', company_id), ('parent_state', '=', 'posted'), ('credit', '>', 0)]")
    move_id = fields.Many2one(related="source_line_id.move_id")
    date = fields.Date(related="source_line_id.date", store=True)
    amount = fields.Monetary(required=True)
    kind = fields.Selection([("repayment", "Repayment / payroll deduction"),
                             ("adjustment", "Credit adjustment"), ("reversal", "Charge reversal")],
                            default="repayment", required=True)
    _source_unique = models.Constraint("UNIQUE(credit_id, source_line_id)", "This settlement is already linked to this charge.")

    @api.constrains("source_line_id", "credit_id", "amount", "kind")
    def _check_allocation(self):
        lock_sources(self.env, self.source_line_id | self.credit_id.source_line_id)
        for record in self:
            line, credit = record.source_line_id, record.credit_id
            if (line.parent_state != "posted" or line.credit <= 0 or line.company_id != credit.company_id
                    or line.account_id != credit.source_line_id.account_id or line.currency_id != credit.currency_id):
                raise ValidationError(_("Link a posted company-currency credit on the charge's receivable account."))
            if line.partner_id != credit.partner_id or line.date < credit.charge_date or record.amount <= 0:
                raise ValidationError(_("Settlement partner/date/amount does not match the charge."))
            total = sum(self.search([("source_line_id", "=", line.id)]).mapped("amount"))
            if credit.currency_id.compare_amounts(total, line.credit) > 0:
                raise ValidationError(_("Allocations exceed the source credit."))
            if credit.currency_id.compare_amounts(sum(credit.allocation_ids.mapped("amount")), credit.amount) > 0:
                raise ValidationError(_("Settlements exceed the charge balance."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.credit_id.message_post(body=_("Assigned settlement %s: %s (%s)",
                                                  record.move_id.name, record.amount, record.kind))
        return records

    def write(self, values):
        if "credit_id" in values or "source_line_id" in values:
            raise UserError(_("Remove and recreate the allocation to change its accounting source."))
        result = super().write(values)
        for credit in self.credit_id:
            credit.message_post(body=_("Updated settlement allocation: %s", str(values)))
        return result

    def unlink(self):
        for record in self:
            record.credit_id.message_post(body=_("Removed settlement allocation %s: %s", record.move_id.name, record.amount))
        return super().unlink()
