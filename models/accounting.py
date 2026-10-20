from odoo import models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def tha_check_staff_credit_links(self):
        # sudo only checks existence, so non-register users cannot invalidate links.
        linked = self.env["tha.staff.credit"].sudo().search_count([("source_move_id", "in", self.ids)])
        linked += self.env["tha.staff.credit.allocation"].sudo().search_count([("move_id", "in", self.ids)])
        if linked:
            raise UserError(_("This entry is linked to Staff Credit. Ask a Staff Credit manager to remove its allocations first."))

    def write(self, values):
        if {"state", "date", "company_id", "journal_id", "partner_id"} & values.keys():
            protected = self.filtered(lambda m: any(
                key in values and values[key] != (m[key].id if hasattr(m[key], "id") else m[key])
                for key in ("state", "date", "company_id", "journal_id", "partner_id")))
            protected.tha_check_staff_credit_links()
        return super().write(values)


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def tha_check_staff_credit_links(self):
        if (self.env["tha.staff.credit"].sudo().search_count([("source_line_id", "in", self.ids)])
                or self.env["tha.staff.credit.allocation"].sudo().search_count([("source_line_id", "in", self.ids)])):
            raise UserError(_("Remove Staff Credit links before modifying or deleting this journal item."))

    def write(self, values):
        if {"debit", "credit", "balance", "amount_currency", "currency_id", "account_id", "partner_id", "date", "company_id", "move_id"} & values.keys():
            self.tha_check_staff_credit_links()
        return super().write(values)

    def unlink(self):
        self.tha_check_staff_credit_links()
        return super().unlink()
