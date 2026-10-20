import base64
import io
from dateutil.relativedelta import relativedelta
import xlsxwriter

from odoo import fields, models, Command, _
from odoo.exceptions import UserError

from ..models.staff_credit import CATEGORIES


class CreditReport(models.TransientModel):
    _name = "tha.staff.credit.report"
    _description = "Monthly Staff Credit Report"
    _check_company_auto = True

    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    month = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(day=1))
    currency_id = fields.Many2one(related="company_id.currency_id")
    employee_id = fields.Many2one("hr.employee.public", check_company=True)
    department_id = fields.Many2one("hr.department", check_company=True)
    category = fields.Selection(CATEGORIES)
    status = fields.Selection([("all", "All"), ("open", "Open at month end"),
                               ("settled", "Settled at month end")], default="all", required=True)
    line_ids = fields.One2many("tha.staff.credit.report.line", "wizard_id")
    audit_ids = fields.One2many("tha.staff.credit.report.audit", "wizard_id")
    opening = fields.Monetary(readonly=True)
    charges = fields.Monetary(readonly=True)
    reductions = fields.Monetary(readonly=True)
    closing = fields.Monetary(readonly=True)
    gl_balance = fields.Monetary(readonly=True)
    difference = fields.Monetary(readonly=True)
    unlinked_debits = fields.Monetary(readonly=True)
    unapplied_credits = fields.Monetary(readonly=True)
    file_data = fields.Binary(readonly=True, attachment=False)
    filename = fields.Char(readonly=True)

    def _data(self):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise UserError(_("Select a company in your allowed companies."))
        config = self.env["tha.staff.credit.config"].search([("company_id", "=", self.company_id.id)], limit=1)
        if not config:
            raise UserError(_("Configure the Staff Credit receivable account first."))
        start = self.month.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        previous = start + relativedelta(days=-1)
        credits = self.env["tha.staff.credit"].search([
            ("company_id", "=", self.company_id.id), ("charge_date", "<=", end),
        ])
        allocations = self.env["tha.staff.credit.allocation"].search([
            ("company_id", "=", self.company_id.id), ("source_line_id.parent_state", "=", "posted"),
            ("date", "<=", end),
        ])
        by_credit = {}
        used = {}
        for allocation in allocations:
            by_credit.setdefault(allocation.credit_id.id, []).append(allocation)
            used[allocation.source_line_id.id] = used.get(allocation.source_line_id.id, 0) + allocation.amount
        debit_used = {}
        opening = charges = reductions = 0.0
        rows, movements = [], []
        for credit in credits:
            debit_used[credit.source_line_id.id] = debit_used.get(credit.source_line_id.id, 0) + credit.amount
            items = by_credit.get(credit.id, [])
            prior = sum(a.amount for a in items if a.date < start)
            actual = sum(a.amount for a in items if a.date >= start)
            balance = credit.amount - prior
            closing = balance - actual
            opening += credit.amount if credit.charge_date < start else 0
            opening -= prior
            charges += credit.amount if credit.charge_date >= start else 0
            reductions += actual
            if ((self.employee_id and credit.employee_id != self.employee_id)
                    or (self.department_id and credit.department_id != self.department_id)
                    or (self.category and credit.category != self.category)
                    or (self.status == "open" and self.currency_id.is_zero(closing))
                    or (self.status == "settled" and not self.currency_id.is_zero(closing))):
                continue
            rows.append({
                "credit_id": credit.id, "name": credit.name, "date": credit.charge_date,
                "staff": credit.employee_id.name, "department": credit.department_id.name,
                "description": credit.description, "amount": credit.amount, "prior": prior,
                "balance": balance, "planned": sum(s.amount for s in credit.schedule_ids if start <= s.due_date <= end),
                "times": "%s/%s" % (credit.paid_installments(previous), len(credit.schedule_ids)),
                "remark": "; ".join(filter(None, [credit.remark, credit.warning])),
                "reference": credit.source_move_id.name, "actual": actual, "closing": closing,
            })
            movements.append({"name": credit.name, "date": credit.charge_date, "kind": "Charge",
                              "reference": credit.source_move_id.name, "amount": credit.amount})
            labels = dict(self.env["tha.staff.credit.allocation"]._fields["kind"].selection)
            movements.extend({"name": credit.name, "date": a.date, "kind": labels[a.kind],
                              "reference": a.move_id.name, "amount": -a.amount} for a in items)
        gl_lines = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id), ("account_id", "=", config.account_id.id),
            ("parent_state", "=", "posted"), ("date", "<=", end),
        ], order="date, id")
        audit = []
        unlinked_debits = unapplied_credits = 0.0
        for line in gl_lines:
            debit = line.debit - debit_used.get(line.id, 0)
            credit = line.credit - used.get(line.id, 0)
            unlinked_debits += debit
            unapplied_credits += credit
            if not self.currency_id.is_zero(debit) or not self.currency_id.is_zero(credit):
                audit.append({"source_line_id": line.id, "date": line.date, "reference": line.move_id.name,
                              "partner": line.partner_id.display_name or "", "debit": debit, "credit": credit})
        closing = opening + charges - reductions
        gl_balance = sum(gl_lines.mapped("balance"))
        summary = {"opening": opening, "charges": charges, "reductions": reductions,
                   "closing": closing, "gl_balance": gl_balance, "difference": gl_balance - closing,
                   "unlinked_debits": unlinked_debits, "unapplied_credits": unapplied_credits}
        return {"rows": rows, "movements": sorted(movements, key=lambda m: (m["date"], m["name"])),
                "audit": audit, "summary": summary, "start": start, "end": end,
                "previous_label": previous.strftime("%b'%y"), "month_label": start.strftime("%b'%y")}

    def action_preview(self):
        data = self._data()
        self.write(dict(data["summary"],
                        line_ids=[Command.clear()] + [Command.create(r) for r in data["rows"]],
                        audit_ids=[Command.clear()] + [Command.create(r) for r in data["audit"]]))
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "current"}

    def _xlsx(self, data):
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False,
                                               "strings_to_urls": False})
        header = workbook.add_format({"bold": True, "bg_color": "#DEEAF6", "border": 1, "text_wrap": True})
        money = workbook.add_format({"num_format": "#,##0.00", "border": 1})
        text = workbook.add_format({"border": 1, "text_wrap": True, "valign": "top"})
        date = workbook.add_format({"num_format": "dd-mmm-yy", "border": 1})
        sheet = workbook.add_worksheet("Staff Credit")
        sheet.merge_range(0, 0, 0, 12, "%s — Staff Credit — %s" % (self.company_id.name, data["month_label"]), header)
        sheet.merge_range(1, 0, 1, 12, "Monthly amount is PLANNED. Balance is before this month's deductions. Currency: %s" % self.currency_id.name, text)
        headings = ["No", "Date", "Staff name", "Department", "Name (Patient & Others)", "100% Bill",
                    "Settlement up to " + data["previous_label"], "Balance", data["month_label"] + " (planned)",
                    "Times", "Remark", "System Reference", "Month-end balance"]
        for col, title in enumerate(headings):
            sheet.write(3, col, title, header)
        for index, row in enumerate(data["rows"], 4):
            values = [row[k] for k in ("name", "date", "staff", "department", "description", "amount",
                                       "prior", "balance", "planned", "times", "remark", "reference", "closing")]
            for col, value in enumerate(values):
                sheet.write(index, col, value, money if col in (5, 6, 7, 8, 12) else date if col == 1 else text)
        total_row = 4 + len(data["rows"])
        sheet.write(total_row, 0, "Filtered totals", header)
        for col, key in ((5, "amount"), (6, "prior"), (7, "balance"), (8, "planned"), (12, "closing")):
            sheet.write_number(total_row, col, sum(r[key] for r in data["rows"]), money)
        sheet.set_column(0, 0, 18)
        sheet.set_column(1, 3, 19)
        sheet.set_column(4, 4, 46)
        sheet.set_column(5, 9, 18)
        sheet.set_column(10, 11, 25)
        sheet.set_column(12, 12, 20)
        sheet.set_row(3, 38)
        sheet.freeze_panes(4, 4)
        sheet.autofilter(3, 0, max(3, total_row - 1), 12)
        sheet.set_landscape()
        sheet.set_paper(8)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, 3)
        sheet.print_area(0, 0, total_row, 12)
        movements = workbook.add_worksheet("Movements")
        for col, title in enumerate(["Charge", "Date", "Movement type", "Accounting reference", "Signed amount"]):
            movements.write(0, col, title, header)
        for index, row in enumerate(data["movements"], 1):
            for col, key in enumerate(("name", "date", "kind", "reference", "amount")):
                movements.write(index, col, row[key], money if col == 4 else date if col == 1 else text)
        movements.set_column(0, 4, 27)
        movements.freeze_panes(1, 0)
        summary = workbook.add_worksheet("GL Reconciliation")
        summary.merge_range(0, 0, 0, 4, "COMPANY-WIDE totals, independent of staff/category/status filters", header)
        for index, (key, value) in enumerate(data["summary"].items(), 2):
            summary.write(index, 0, key.replace("_", " ").title(), text)
            summary.write_number(index, 1, value, money)
        offset = 13
        for col, title in enumerate(["Journal item ID", "Date", "Reference", "Partner", "Unlinked debit", "Unapplied credit"]):
            summary.write(offset, col, title, header)
        for index, row in enumerate(data["audit"], offset + 1):
            for col, key in enumerate(("source_line_id", "date", "reference", "partner", "debit", "credit")):
                summary.write(index, col, row[key], money if col >= 4 else date if col == 1 else text)
        summary.set_column(0, 5, 27)
        workbook.close()
        return output.getvalue()

    def action_excel(self):
        data = self._data()
        self.write({"file_data": base64.b64encode(self._xlsx(data)),
                    "filename": "staff_credit_%s.xlsx" % data["start"].strftime("%Y_%m")})
        return {"type": "ir.actions.act_url", "url": "/web/content/%s/%s/file_data/%s?download=true" %
                (self._name, self.id, self.filename), "target": "self"}

    def action_pdf(self):
        self.ensure_one()
        return self.env.ref("tha_vhg_staff_credit_report.action_report_pdf").report_action(self)


class CreditReportLine(models.TransientModel):
    _name = "tha.staff.credit.report.line"
    _description = "Monthly Staff Credit Row"

    wizard_id = fields.Many2one("tha.staff.credit.report", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id", store=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    credit_id = fields.Many2one("tha.staff.credit")
    name = fields.Char()
    date = fields.Date()
    staff = fields.Char()
    department = fields.Char()
    description = fields.Char()
    amount = fields.Monetary()
    prior = fields.Monetary()
    balance = fields.Monetary()
    planned = fields.Monetary()
    actual = fields.Monetary()
    closing = fields.Monetary()
    times = fields.Char()
    remark = fields.Char()
    reference = fields.Char()


class CreditReportAudit(models.TransientModel):
    _name = "tha.staff.credit.report.audit"
    _description = "Unallocated Staff Credit Journal Item"

    wizard_id = fields.Many2one("tha.staff.credit.report", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="wizard_id.company_id", store=True)
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    source_line_id = fields.Many2one("account.move.line")
    date = fields.Date()
    reference = fields.Char()
    partner = fields.Char()
    debit = fields.Monetary()
    credit = fields.Monetary()


class CreditPDF(models.AbstractModel):
    _name = "report.tha_vhg_staff_credit_report.monthly_pdf"
    _description = "Staff Credit PDF"

    def _get_report_values(self, docids, data=None):
        docs = self.env["tha.staff.credit.report"].browse(docids)
        docs.check_access("read")
        return {"doc_ids": docids, "doc_model": docs._name, "docs": docs,
                "reports": [(wizard, wizard._data()) for wizard in docs]}
