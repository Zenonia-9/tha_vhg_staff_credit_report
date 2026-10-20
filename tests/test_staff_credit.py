import base64
import csv
import io
import zipfile
from datetime import date
from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..wizard.credit_import import COLUMNS


@tagged("post_install", "-at_install")
class TestStaffCredit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].search([("name", "ilike", "THUKHA SAYTANAR")], limit=1)
        if not cls.company:
            raise AssertionError("Focused THA validation requires the Thukhasaytanar company")
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.account = cls.env["account.account"].with_company(cls.company).search([
            ("company_ids", "in", cls.company.id), ("code", "=", "130100")], limit=1)
        cls.offset = cls.env["account.account"].search([
            ("company_ids", "in", cls.company.id), ("account_type", "=", "expense")], limit=1)
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id), ("type", "=", "general")], limit=1)
        if not cls.journal:
            cls.journal = cls.env["account.journal"].create({"name": "Staff Credit TEST", "code": "SCTST",
                                                            "type": "general", "company_id": cls.company.id})
        cls.config = cls.env["tha.staff.credit.config"].search([("company_id", "=", cls.company.id)])
        if not cls.config:
            cls.config = cls.env["tha.staff.credit.config"].create({"company_id": cls.company.id, "account_id": cls.account.id})
        cls.department = cls.env["hr.department"].create({"name": "Staff Credit TEST Transport", "company_id": cls.company.id})
        cls.employee = cls.env["hr.employee"].create({"name": "Staff Credit TEST Staff", "company_id": cls.company.id,
                                                    "department_id": cls.department.id})
        cls.partner = cls.employee.work_contact_id
        cls.partner.ref = "SC-TEST-STAFF"

    def _move(self, amount, day, credit=False, partner=None):
        move = self.env["account.move"].create({
            "journal_id": self.journal.id, "company_id": self.company.id, "date": day,
            "ref": "STAFF CREDIT AUTOMATED TEST", "line_ids": [
                Command.create({"account_id": self.account.id, "partner_id": (partner or self.partner).id,
                                "date_maturity": day, "credit" if credit else "debit": amount}),
                Command.create({"account_id": self.offset.id, "debit" if credit else "credit": amount}),
            ],
        })
        move.action_post()
        return move.line_ids.filtered(lambda line: line.account_id == self.account)

    def _charge(self, amount=470000, day="2026-03-26", source=None, count=3):
        source = source or self._move(amount, day)
        charge = self.env["tha.staff.credit"].create({
            "company_id": self.company.id, "employee_id": self.employee.id,
            "partner_id": self.partner.id, "department_id": self.department.id,
            "charge_date": day, "category": "hospital", "description": "Staff Credit TEST patient and other charges",
            "source_line_id": source.id, "amount": amount, "start_month": "2026-09-01",
            "installment_count": count,
        })
        charge.action_generate_schedule()
        return charge

    def _settle(self, charge, amount, day="2026-09-30", source=None, kind="repayment"):
        return self.env["tha.staff.credit.allocation"].create({
            "credit_id": charge.id, "source_line_id": (source or self._move(amount, day, True)).id,
            "amount": amount, "kind": kind,
        })

    def _report(self, month="2026-10-01", **values):
        values.setdefault("employee_id", self.employee.id)
        return self.env["tha.staff.credit.report"].create(dict(company_id=self.company.id, month=month, **values))

    def test_reference_and_historical_cutoff(self):
        charge = self._charge()
        # MMK in this local chart rounds to cents; use the agreed whole-kyat plan.
        for line, amount in zip(charge.schedule_ids.sorted("due_date"), (156667, 156667, 156666)):
            line.amount = amount
        self._settle(charge, 156667)
        report = self._report()
        row = report._data()["rows"][0]
        self.assertEqual((row["amount"], row["prior"], row["balance"], row["planned"], row["times"]),
                         (470000, 156667, 313333, 156667, "1/3"))
        self._settle(charge, 156667, "2026-11-30")
        self.assertEqual(report._data()["rows"][0], row)
        self.assertEqual(report._data()["summary"]["difference"], 0)
        report.action_preview()
        self.assertEqual(report.line_ids.balance, 313333)

    def test_split_source_and_credit_caps(self):
        debit = self._move(300, "2026-03-26")
        first = self._charge(100, source=debit)
        second = self._charge(200, source=debit)
        credit = self._move(150, "2026-09-30", True)
        self._settle(first, 50, source=credit)
        self._settle(second, 100, source=credit)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._charge(1, source=debit)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            second.allocation_ids.amount = 101
        self.assertEqual(self._report()._data()["summary"]["difference"], 0)

    def test_partial_skip_and_locked_installments(self):
        charge = self._charge(300)
        self._settle(charge, 50)
        self.assertEqual(charge.paid_installments(date(2026, 9, 30)), 0)
        charge.schedule_ids.sorted("due_date")[-1].due_date = "2027-01-31"
        self._settle(charge, 50, "2026-10-02")
        self.assertEqual(charge.paid_installments(date(2026, 10, 31)), 1)
        first = charge.schedule_ids.sorted("due_date")[0]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            first.amount = 99
        with self.assertRaises(UserError), self.env.cr.savepoint():
            first.unlink()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            charge.schedule_ids[-1].due_date = "2026-08-31"
        self.assertEqual(self._report("2026-12-01")._data()["rows"][0]["planned"], 0)

    def test_unmatched_and_filtered_reconciliation(self):
        charge = self._charge(300)
        self._settle(charge, 80, kind="adjustment")
        self._move(27, "2026-09-01")
        self._move(11, "2026-10-01", True)
        report = self._report(category="meals")
        data = report._data()
        self.assertFalse(data["rows"])
        self.assertEqual(data["summary"]["unlinked_debits"], 27)
        self.assertEqual(data["summary"]["unapplied_credits"], 11)
        self.assertEqual(data["summary"]["difference"], 16)
        self.assertEqual(charge.paid_installments(date(2026, 10, 31)), 0)

    def test_reversal_and_accounting_guard(self):
        charge = self._charge(300)
        settlement = self._settle(charge, 300, "2026-10-15", kind="reversal")
        self.assertEqual(self._report(status="settled")._data()["rows"][0]["closing"], 0)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            charge.source_move_id.button_draft()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            settlement.source_line_id.write({"partner_id": False})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._settle(charge, 1)

    def test_reconciled_suggestion_requires_confirmation(self):
        charge = self._charge(300)
        source = self._move(100, "2026-09-30", True)
        (charge.source_line_id | source).reconcile()
        result = charge.action_suggest_settlements()
        self.assertFalse(charge.allocation_ids)
        wizard = self.env[result["res_model"]].browse(result["res_id"])
        self.assertEqual(wizard.line_ids.amount, 100)
        wizard.action_confirm()
        self.assertEqual(charge.allocation_ids.amount, 100)
        with self.assertRaises(UserError):
            charge.action_suggest_settlements()

    def test_partly_registered_debit_is_not_an_unambiguous_match(self):
        source = self._move(300, "2026-03-26")
        charge = self._charge(100, source=source)
        payment = self._move(50, "2026-09-30", True)
        (source | payment).reconcile()
        with self.assertRaises(UserError):
            charge.action_suggest_settlements()
        other = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.config.company_id = other

    def test_security_and_company_isolation(self):
        charge = self._charge(300)
        user = self.env["res.users"].create({"name": "Staff Credit Reader TEST", "login": "staff-credit-reader-test",
            "company_id": self.company.id, "company_ids": [Command.set([self.company.id])],
            "group_ids": [Command.set([self.env.ref("tha_vhg_staff_credit_report.group_reader").id])]})
        self.assertEqual(charge.with_user(user).amount, 300)
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            charge.with_user(user).write({"remark": "No"})
        other = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        hidden = charge.with_user(user).with_context(allowed_company_ids=[other.id])
        with self.assertRaises(AccessError):
            hidden.check_access("read")
        outsider = self.env["res.users"].create({"name": "Staff Credit Outsider TEST", "login": "staff-credit-outsider-test",
            "company_id": self.company.id, "company_ids": [Command.set([self.company.id])],
            "group_ids": [Command.set([self.env.ref("base.group_user").id])]})
        with self.assertRaises(AccessError):
            charge.with_user(outsider).check_access("read")
        attachment = self.env["ir.attachment"].create({"name": "test-patient.txt", "datas": base64.b64encode(b"private"),
                                                       "res_model": charge._name, "res_id": charge.id})
        with self.assertRaises(AccessError):
            attachment.with_user(outsider).check_access("read")

    def test_xlsx_and_pdf_render(self):
        self._charge(300)
        report = self._report()
        data = report._data()
        with zipfile.ZipFile(io.BytesIO(report._xlsx(data))) as archive:
            sheet = etree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            self.assertEqual(sheet.xpath("string(//s:c[@r='F5']/s:v)", namespaces=ns), "300")
            self.assertEqual(len(archive.namelist()) > 8, True)
        content, _ = self.env["ir.actions.report"].with_context(force_report_rendering=True)._render_qweb_pdf(
            "tha_vhg_staff_credit_report.action_report_pdf", res_ids=report.ids)
        self.assertTrue(content.startswith(b"%PDF"))

    def test_views_load_for_normal_manager_in_xml_development_mode(self):
        for model, types in (
            ("tha.staff.credit", ("form", "list", "search")),
            ("tha.staff.credit.report", ("form",)),
            ("tha.staff.credit.import", ("form",)),
            ("tha.staff.credit.config", ("list",)),
            ("tha.staff.credit.suggestion", ("form",)),
        ):
            result = self.env[model].with_user(self.env.ref("base.user_admin")).get_views(
                [(False, view_type) for view_type in types], options={})
            for view_type in types:
                self.assertTrue(result["views"][view_type]["arch"], model)

    def test_staff_credit_menu_uses_visible_other_reports_parent(self):
        menu = self.env.ref("tha_vhg_staff_credit_report.menu_staff_credit")
        parent = self.env.ref("tha_vhg_daily_cash_register.menu_other_reports")
        self.assertEqual(menu.parent_id, parent)
        visible = self.env["ir.ui.menu"].with_user(self.env.ref("base.user_admin")).load_menus(False)
        self.assertIn(menu.id, visible)
        self.assertIn(menu.id, visible[parent.id]["children"])
        self.assertEqual(visible[menu.id]["app_id"], visible[parent.id]["app_id"])

    def _native_options(self, **previous):
        report = self.env.ref("tha_vhg_staff_credit_report.native_staff_credit_report")
        options = {"date": {"date_from": "2026-10-01", "date_to": "2026-10-31", "mode": "range", "filter": "custom"},
                   "staff_credit_employee": [{"id": self.employee.id, "selected": True}]}
        options.update(previous)
        return report, report.get_options(options)

    def test_native_report_matches_register_and_opens_charge(self):
        charge = self._charge(300)
        self._settle(charge, 100)
        report, options = self._native_options()
        lines = report._get_lines(options)
        self.assertEqual(len(lines[0]["columns"]), len(options["columns"]),
                         "The native header derives its column labels from the first row")
        row = next(line for line in lines if line.get("caret_options") == "tha.staff.credit")
        values = {cell["expression_label"]: cell["no_format"] for cell in row["columns"]}
        self.assertEqual((values["amount"], values["prior"], values["balance"], values["planned"], values["times"]),
                         (300, 100, 200, 100, "1/3"))
        self.assertEqual(options["date"]["date_from"], "2026-10-01")
        self.assertEqual(report.dispatch_report_action(options, "open_staff_credit", {"line_id": row["id"]})["res_id"], charge.id)
        action = self.env.ref("tha_vhg_staff_credit_report.menu_monthly_report").action
        self.assertEqual((action._name, action.tag), ("ir.actions.client", "account_report"))
        self.assertEqual(report.get_report_information(options)["lines"], lines)

    def test_native_status_department_search_and_cutoff(self):
        charge = self._charge(300)
        self._settle(charge, 300, "2026-11-30")
        report, options = self._native_options(staff_credit_status=[{"id": "open", "selected": True}],
            staff_credit_department=[{"id": self.department.id, "selected": True}], filter_search_bar="patient")
        self.assertEqual(len([line for line in report._get_lines(options) if line.get("caret_options") == "tha.staff.credit"]), 1)
        report, options = self._native_options(staff_credit_status=[{"id": "settled", "selected": True}])
        self.assertFalse([line for line in report._get_lines(options) if line.get("caret_options") == "tha.staff.credit"])

    def test_native_unconfigured_company_and_access(self):
        other = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        report = self.env.ref("tha_vhg_staff_credit_report.native_staff_credit_report").with_context(allowed_company_ids=other.ids)
        options = report.get_options({})
        self.assertIn("No Staff Credit account", options["staff_credit_notice"])
        self.assertTrue(report._get_lines(options))
        user = self.env["res.users"].create({"name": "Native report outsider TEST", "login": "native-credit-outsider-test",
            "company_id": self.company.id, "company_ids": [Command.set([self.company.id])],
            "group_ids": [Command.set([self.env.ref("account.group_account_readonly").id])]})
        with self.assertRaises(AccessError):
            self.env.ref("tha_vhg_staff_credit_report.native_staff_credit_report").with_user(user).get_options({})

    def test_native_pdf_xlsx_exports(self):
        self._charge(300)
        report, options = self._native_options()
        with zipfile.ZipFile(io.BytesIO(report.export_to_xlsx(options)["file_content"])) as archive:
            self.assertIn("300", archive.read("xl/worksheets/sheet1.xml").decode())
        pdf = report.with_context(force_report_rendering=True).dispatch_report_action(options, "export_to_pdf")["file_content"]
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_rounding_and_reports_do_not_post_accounting(self):
        charge = self._charge(100, count=3)
        self.assertEqual(sum(charge.schedule_ids.mapped("amount")), 100)
        source_values = charge.source_line_id.read(["debit", "credit", "balance", "amount_residual", "write_date"])
        count = self.env["account.move"].search_count([("company_id", "=", self.company.id)])
        report = self._report()
        report.action_preview()
        report.action_excel()
        report._data()
        self.assertEqual(charge.source_line_id.read(["debit", "credit", "balance", "amount_residual", "write_date"]), source_values)
        self.assertEqual(self.env["account.move"].search_count([("company_id", "=", self.company.id)]), count)

    def test_wrong_sources_and_duplicate_allocations(self):
        charge = self._charge(300)
        wrong_partner = self.env["res.partner"].create({"name": "Different debtor TEST"})
        bad_credit = self._move(30, "2026-09-30", True, partner=wrong_partner)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._settle(charge, 30, source=bad_credit)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._settle(charge, 30, source=charge.source_line_id)
        self._settle(charge, 30)
        other_company = self.env["res.company"].search([("id", "!=", self.company.id)], limit=1)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            charge.write({"company_id": other_company.id})

    def test_import_validation_atomicity_and_duplicate(self):
        debit = self._move(300, "2026-03-26")
        number = debit.move_id.line_ids.sorted("id").ids.index(debit.id) + 1
        row = dict(row_type="charge", external_key="TEST-IMPORT", staff_identifier=self.partner.ref,
                   department=self.department.name, charge_date="2026-03-26", category="hospital",
                   description="TEST CSV", move_reference=debit.move_id.name, journal_code=self.journal.code,
                   line_number=number, amount=300, start_month="2026-09-01", installment_count=3)
        def upload(rows):
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            return base64.b64encode(output.getvalue().encode())
        wizard = self.env["tha.staff.credit.import"].create({"company_id": self.company.id, "upload": upload([row])})
        wizard.action_validate()
        self.assertIn("Preview only", wizard.result)
        domain = [("external_key", "=", "TEST-IMPORT")]
        self.assertFalse(self.env["tha.staff.credit"].search(domain))
        wizard.upload = upload([row, dict(row, external_key="TEST-BAD", staff_identifier="MISSING")])
        wizard.action_import()
        self.assertIn("Row 3", wizard.result)
        self.assertFalse(self.env["tha.staff.credit"].search(domain))
        wizard.upload = upload([row])
        wizard.action_import()
        self.assertIn("Import complete", wizard.result)
        self.assertEqual(self.env["tha.staff.credit"].search_count(domain), 1)
        wizard.action_import()
        self.assertIn("Duplicate", wizard.result)
