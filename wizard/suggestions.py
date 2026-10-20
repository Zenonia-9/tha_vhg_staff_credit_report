from odoo import fields, models, Command


class Suggestion(models.TransientModel):
    _name = "tha.staff.credit.suggestion"
    _description = "Review Reconciled Settlement Suggestions"

    credit_id = fields.Many2one("tha.staff.credit", required=True)
    company_id = fields.Many2one(related="credit_id.company_id", store=True)
    line_ids = fields.One2many("tha.staff.credit.suggestion.line", "wizard_id")

    def action_confirm(self):
        self.ensure_one()
        self.credit_id.write({"allocation_ids": [Command.create({
            "source_line_id": line.source_line_id.id, "amount": line.amount, "kind": line.kind,
        }) for line in self.line_ids if line.selected]})
        return {"type": "ir.actions.act_window_close"}


class SuggestionLine(models.TransientModel):
    _name = "tha.staff.credit.suggestion.line"
    _description = "Proposed Settlement"

    wizard_id = fields.Many2one("tha.staff.credit.suggestion", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    selected = fields.Boolean(default=True)
    source_line_id = fields.Many2one("account.move.line", required=True)
    amount = fields.Monetary(required=True)
    kind = fields.Selection([("repayment", "Repayment / payroll deduction"),
                             ("adjustment", "Credit adjustment"), ("reversal", "Charge reversal")],
                            default="repayment", required=True)
