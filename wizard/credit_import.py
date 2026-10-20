import base64
import csv
import io
import zipfile
from datetime import date, datetime

import xlsxwriter
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError


COLUMNS = ["row_type", "external_key", "staff_identifier", "department", "charge_date", "category",
           "description", "move_reference", "journal_code", "line_number", "amount", "start_month",
           "installment_count", "due_date", "remark", "kind"]


class ImportRollback(Exception):
    pass


class CreditImport(models.TransientModel):
    _name = "tha.staff.credit.import"
    _description = "Validate and Import Staff Credit Workbook"

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
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet("Import")
        header_format = workbook.add_format({"bold": True, "bg_color": "#49354F", "font_color": "#FFFFFF",
                                             "text_wrap": True, "valign": "vcenter", "border": 1})
        text_format = workbook.add_format({"num_format": "@"})
        amount_format = workbook.add_format({"num_format": "0.00"})
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, 5, len(COLUMNS) - 1)
        sheet.set_row(0, 32)
        widths = [14, 20, 20, 20, 14, 14, 30, 24, 14, 12, 14, 14, 18, 14, 28, 14]
        for col, (name, width) in enumerate(zip(COLUMNS, widths)):
            sheet.write(0, col, name, header_format)
            sheet.set_column(col, col, width, text_format)
        rows = [
            dict(row_type="charge", external_key="EXAMPLE-001", staff_identifier="STAFF-001",
                 department="Transport", charge_date="2026-03-26", category="hospital", description="Example only",
                 move_reference="MISC/2026/0001", journal_code="MISC", line_number=1, amount=470000,
                 start_month="2026-09-01", installment_count=3),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-09-30", amount=156667),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-10-31", amount=156667),
            dict(row_type="schedule", external_key="EXAMPLE-001", due_date="2026-11-30", amount=156666),
            dict(row_type="settlement", external_key="EXAMPLE-001", move_reference="MISC/2026/0002",
                 journal_code="MISC", line_number=2, amount=156667, kind="repayment"),
        ]
        for row_number, row in enumerate(rows, 1):
            for col, name in enumerate(COLUMNS):
                value = row.get(name)
                if value is None:
                    continue
                cell_format = amount_format if name == "amount" else text_format
                if name == "line_number" or name == "installment_count":
                    sheet.write_number(row_number, col, value)
                elif name == "amount":
                    sheet.write_number(row_number, col, value, cell_format)
                else:
                    sheet.write(row_number, col, value, cell_format)

        instructions = workbook.add_worksheet("Instructions")
        instructions.set_column("A:A", 24)
        instructions.set_column("B:B", 105)
        instructions.write_row(0, 0, ["Topic", "Instructions"], header_format)
        notes = [
            ("Before importing", "Replace every EXAMPLE value. Import metadata and links to existing posted accounting entries; this workbook never creates accounting entries."),
            ("Row order", "Put all charge rows first, schedule rows second, and settlement rows last. Keep the exact column names in the Import sheet."),
            ("charge", "One row per charge. Use the employee work-contact Reference, exact department name, posted debit entry reference, journal code and 1-based journal-item line number."),
            ("schedule", "One row per planned installment. Use the same external_key as its charge, due_date in YYYY-MM-DD format, and amount. The amounts must total the charge."),
            ("settlement", "One row per allocation to a charge. Link an existing posted credit entry and choose repayment, adjustment or reversal."),
            ("Dates and amounts", "Use YYYY-MM-DD dates and plain numeric amounts. Do not type currency symbols or thousands separators."),
            ("Validate only", "Checks the entire workbook and saves no register records."),
            ("Validate and import", "Saves all valid rows together. If any row fails, the entire import is rolled back."),
        ]
        for row_number, values in enumerate(notes, 1):
            instructions.write_row(row_number, 0, values)
        workbook.close()
        self.write({"template_data": base64.b64encode(output.getvalue()),
                    "template_name": "staff_credit_import.xlsx"})
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

    def _xlsx_rows(self, content):
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            if "Import" not in workbook.sheetnames:
                raise UserError(_("The Excel workbook must contain an Import sheet."))
            sheet = workbook["Import"]
            if sheet.max_row > 5001:
                raise UserError(_("Import between 1 and 5000 rows per file."))
            header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            header = [self._cell_text(value) for value in header_row]
            while header and not header[-1]:
                header.pop()
            if header != COLUMNS:
                raise UserError(_("Excel columns must match the downloaded template exactly."))
            rows = []
            for values in sheet.iter_rows(min_row=2, max_col=len(COLUMNS), values_only=True):
                if not any(value is not None for value in values):
                    continue
                rows.append({name: self._cell_text(values[index]) for index, name in enumerate(COLUMNS)})
            return rows
        finally:
            workbook.close()

    def _read_rows(self):
        decoded = base64.b64decode(self.upload)
        if (self.upload_name or "").lower().endswith(".csv"):
            reader = csv.DictReader(io.StringIO(decoded.decode("utf-8-sig")))
            if reader.fieldnames != COLUMNS:
                raise UserError(_("CSV columns must match the downloaded template exactly."))
            return [{k: (v or "").strip() for k, v in row.items()} for row in reader]
        if not (self.upload_name or "").lower().endswith(".xlsx"):
            raise UserError(_("Upload an .xlsx Excel workbook or a .csv file."))
        return self._xlsx_rows(decoded)

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
            raise UserError(_("Select an allowed company and upload an Excel workbook."))
        try:
            rows = self._read_rows()
        except (ValueError, UnicodeError, csv.Error, OSError, zipfile.BadZipFile,
                InvalidFileException, KeyError, TypeError) as error:
            raise UserError(_("Invalid Excel workbook or CSV file: %s", str(error))) from error
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

    @staticmethod
    def _cell_text(value):
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()

    def action_validate(self):
        return self._run(True)

    def action_import(self):
        return self._run(False)
