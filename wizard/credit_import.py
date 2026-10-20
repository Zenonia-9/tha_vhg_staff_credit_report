import base64
import csv
import io

from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError


COLUMNS = ["row_type", "external_key", "staff_identifier", "department", "charge_date", "category",
           "description", "move_reference", "journal_code", "line_number", "amount", "start_month",
           "installment_count", "due_date", "remark", "kind"]


class ImportRollback(Exception):
    pass


class CreditImport(models.TransientModel):
    _name = "tha.staff.credit.import"
    _description = "Validate and Import Staff Credit CSV"

    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    upload = fields.Binary(attachment=False)
    upload_name = fields.Char()
    result = fields.Text(readonly=True)
    template_data = fields.Binary(attachment=False, readonly=True)
    template_name = fields.Char(readonly=True)

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new"}

    def action_template(self):
        self.ensure_one()
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows([
            dict(row_type="charge", external_key="EXAMPLE-001", staff_identifier="STAFF-001",
                 department="Transport", charge_date="2026-03-26", category="hospital", description="Example only",
                 move_reference="MISC/2026/0001", journal_code="MISC", line_number=1, amount=470000,
                 start_month="2026-09-01", installment_count=3),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-09-30", amount=156667),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-10-31", amount=156667),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-11-30", amount=156666),
            dict(row_type="settlement", external_key="EXAMPLE-001", move_reference="MISC/2026/0002",
                 journal_code="MISC", line_number=2, amount=156667, kind="repayment"),
        ])
        self.write({"template_data": base64.b64encode(output.getvalue().encode("utf-8-sig")),
                    "template_name": "staff_credit_import.csv"})
        return {"type": "ir.actions.act_url", "target": "self", "url":
                "/web/content/%s/%s/template_data/%s?download=true" % (self._name, self.id, self.template_name)}

    def _source(self, row):
        moves = self.env["account.move"].search([
            ("company_id", "=", self.company_id.id), ("name", "=", row["move_reference"]),
            ("journal_id.code", "=", row["journal_code"]), ("state", "=", "posted"),
        ])
        if len(moves) != 1:
            raise ValidationError(_("Accounting reference must resolve to exactly one posted entry."))
        lines = moves.line_ids.sorted("id")
        number = int(row["line_number"])
        if number < 1 or number > len(lines):
            raise ValidationError(_("Line number is outside this entry (number lines by journal item ID ascending)."))
        return lines[number - 1]

    def _employee(self, identifier):
        # Only public staff data is needed; identifier is the work contact's Reference.
        employees = self.env["hr.employee.public"].with_context(active_test=False).search([
            ("company_id", "=", self.company_id.id), ("work_contact_id.ref", "=", identifier),
        ])
        if not identifier or len(employees) != 1:
            raise ValidationError(_("Staff identifier must match exactly one employee work contact's Reference."))
        return employees

    def _apply_row(self, row):
        key = row["external_key"]
        if not key:
            raise ValidationError(_("An external key is required."))
        credits = self.env["tha.staff.credit"]
        credit = credits.search([("company_id", "=", self.company_id.id), ("external_key", "=", key)])
        row_type = row["row_type"]
        if row_type == "charge":
            if credit:
                raise ValidationError(_("Duplicate charge import key: %s", key))
            employee = self._employee(row["staff_identifier"])
            departments = self.env["hr.department"].search([
                ("company_id", "=", self.company_id.id), ("name", "=", row["department"]),
            ])
            if len(departments) != 1:
                raise ValidationError(_("Department must identify exactly one company department."))
            credit = credits.create({
                "external_key": key, "company_id": self.company_id.id, "employee_id": employee.id,
                "partner_id": employee.work_contact_id.id, "department_id": departments.id,
                "charge_date": row["charge_date"], "category": row["category"],
                "description": row["description"], "source_line_id": self._source(row).id,
                "amount": float(row["amount"]), "start_month": row["start_month"],
                "installment_count": int(row["installment_count"]), "remark": row["remark"],
            })
            credit.action_generate_schedule()
        elif row_type in ("schedule", "settlement"):
            if not credit:
                raise ValidationError(_("Charge key is unresolved; put the charge row before its other rows."))
            if row_type == "settlement":
                self.env["tha.staff.credit.allocation"].create({
                    "credit_id": credit.id, "source_line_id": self._source(row).id,
                    "amount": float(row["amount"]), "kind": row["kind"] or "repayment",
                })
            else:
                due = fields.Date.to_date(row["due_date"])
                schedule = credit.schedule_ids.filtered(lambda s: s.due_date.replace(day=1) == due.replace(day=1))
                values = {"due_date": due, "amount": float(row["amount"])}
                if schedule:
                    schedule.write(values)
                else:
                    self.env["tha.staff.credit.schedule"].create(dict(values, credit_id=credit.id))
        else:
            raise ValidationError(_("Row type must be charge, schedule, or settlement."))
        return credit

    def _run(self, dry_run):
        self.ensure_one()
        self.env["tha.staff.credit"].check_access("create")
        if self.company_id not in self.env.companies or not self.upload:
            raise UserError(_("Select an allowed company and upload a CSV file."))
        try:
            decoded = base64.b64decode(self.upload).decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded))
            if reader.fieldnames != COLUMNS:
                raise UserError(_("CSV columns must match the downloaded template exactly."))
            rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
        except (ValueError, UnicodeError, csv.Error) as error:
            raise UserError(_("Invalid UTF-8 CSV: %s", str(error))) from error
        if not rows or len(rows) > 5000:
            raise UserError(_("Import between 1 and 5000 rows per file."))
        errors, touched = [], self.env["tha.staff.credit"]
        seen = set()
        try:
            # Validate using real model constraints, rolling back every row if any fails.
            with self.env.cr.savepoint():
                for index, row in enumerate(rows, 2):
                    try:
                        identity = (row["row_type"], row["external_key"], row.get("due_date") if row["row_type"] == "schedule"
                                    else (row.get("move_reference"), row.get("journal_code"), row.get("line_number")))
                        if identity in seen:
                            raise ValidationError(_("Duplicate source reference in this file."))
                        seen.add(identity)
                        with self.env.cr.savepoint():
                            touched |= self._apply_row(row)
                    except (UserError, ValidationError, ValueError, KeyError, TypeError) as error:
                        errors.append("Row %s: %s" % (index, str(error)))
                for credit in touched.exists():
                    if credit.warning:
                        errors.append("%s: %s" % (credit.external_key, credit.warning))
                    if len(credit.schedule_ids) != credit.installment_count:
                        errors.append("%s: schedule count differs from installment count" % credit.external_key)
                if errors or dry_run:
                    raise ImportRollback()
        except ImportRollback:
            pass
        self.result = ("No records imported.\n" + "\n".join(errors)) if errors else (
            "%s rows validated. %s" % (len(rows), "Preview only; no records saved." if dry_run else "Import complete."))
        return self._reopen()

    def action_validate(self):
        return self._run(True)

    def action_import(self):
        return self._run(False)
