"""Run through `odoo shell -d THA --no-http`; commits labeled local fixtures.

Never include this file in module data or run it automatically during upgrades.
"""
import json
from pathlib import Path

from odoo import Command


assert env.cr.dbname == "THA", "Demo is restricted to local THA"
company = env["res.company"].search([("name", "=", "THUKHA SAYTANAR CO. Ltd (Victoria Hospital)")])
assert len(company) == 1, "Expected the local hospital company"
env = env(context=dict(env.context, allowed_company_ids=company.ids))
account = env["account.account"].with_company(company).search([
    ("company_ids", "in", company.id), ("code", "=", "130100")])
assert len(account) == 1 and account.reconcile
config = env["tha.staff.credit.config"].search([("company_id", "=", company.id)])
if not config:
    config = env["tha.staff.credit.config"].create({"company_id": company.id, "account_id": account.id})
assert config.account_id == account
offset = env["account.account"].search([
    ("company_ids", "in", company.id), ("account_type", "=", "expense")], limit=1)
journal = env["account.journal"].search([("company_id", "=", company.id), ("code", "=", "SCDMO")])
if not journal:
    journal = env["account.journal"].create({"name": "STAFF CREDIT DEMO ONLY", "code": "SCDMO",
                                             "type": "general", "company_id": company.id})
department = env["hr.department"].search([("company_id", "=", company.id), ("name", "=", "DEMO Staff Credit Transport")])
if not department:
    department = env["hr.department"].create({"name": "DEMO Staff Credit Transport", "company_id": company.id})
employee = env["hr.employee"].search([("company_id", "=", company.id), ("name", "=", "DEMO Staff Credit Employee")])
if not employee:
    employee = env["hr.employee"].create({"name": "DEMO Staff Credit Employee", "company_id": company.id,
                                           "department_id": department.id})
employee.work_contact_id.ref = "SC-DEMO-STAFF"


def move(key, amount, day, credit=False):
    entry = env["account.move"].search([("journal_id", "=", journal.id), ("ref", "=", key)])
    if not entry:
        entry = env["account.move"].create({"journal_id": journal.id, "date": day, "ref": key,
            "line_ids": [Command.create({"account_id": account.id, "partner_id": employee.work_contact_id.id,
                "date_maturity": day, "credit" if credit else "debit": amount}),
                Command.create({"account_id": offset.id, "debit" if credit else "credit": amount})]})
        entry.action_post()
    return entry.line_ids.filtered(lambda line: line.account_id == account)


for key, amount, day, start, count, category in [
    ("SC-DEMO-HOSPITAL", 470000, "2026-03-26", "2026-09-01", 3, "hospital"),
    ("SC-DEMO-MEALS", 250000, "2026-10-01", "2026-10-01", 5, "meals"),
]:
    record = env["tha.staff.credit"].search([("company_id", "=", company.id), ("external_key", "=", key)])
    if not record:
        record = env["tha.staff.credit"].create({"company_id": company.id, "employee_id": employee.id,
            "partner_id": employee.work_contact_id.id, "department_id": department.id, "category": category,
            "description": "DEMO ONLY: " + ("Hospital bill, patient description and supporting evidence" if category == "hospital" else "Meal charges for trip"),
            "charge_date": day, "source_line_id": move(key, amount, day).id, "amount": amount,
            "start_month": start, "installment_count": count, "external_key": key,
            "remark": "LOCAL TEST DATA - not a real patient or staff debt"})
        record.action_generate_schedule()
        if category == "hospital":
            for installment, value in zip(record.schedule_ids.sorted("due_date"), (156667, 156667, 156666)):
                installment.amount = value
            for suffix, settlement_amount, settlement_day in [
                ("SEPT", 156667, "2026-09-30"), ("OCT-PARTIAL", 50000, "2026-10-15")]:
                env["tha.staff.credit.allocation"].create({"credit_id": record.id,
                    "source_line_id": move(key + "-" + suffix, settlement_amount, settlement_day, True).id,
                    "amount": settlement_amount, "kind": "repayment"})

wizard = env["tha.staff.credit.report"].create({"company_id": company.id, "month": "2026-10-01"})
data = wizard._data()
assert data["summary"]["difference"] == 0, data["summary"]
assert not data["audit"], data["audit"]
row = next(r for r in data["rows"] if r["description"].startswith("DEMO ONLY: Hospital"))
assert (row["prior"], row["balance"], row["planned"], row["times"]) == (156667, 313333, 156667, "1/3")
wizard.action_preview()
output = Path("/mnt/custom_addons/tha_vhg_staff_credit_report/artifacts")
output.mkdir(exist_ok=True)
(output / "staff_credit_oct_2026.xlsx").write_bytes(wizard._xlsx(data))
pdf, _ = env["ir.actions.report"]._render_qweb_pdf("tha_vhg_staff_credit_report.action_report_pdf", res_ids=wizard.ids)
assert pdf.startswith(b"%PDF")
(output / "staff_credit_oct_2026.pdf").write_bytes(pdf)
evidence = {"company": company.name, "company_id": company.id, "report_id": wizard.id,
            "summary": data["summary"], "rows": data["rows"], "audit": data["audit"]}
(output / "demo_validation.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
env.cr.commit()
print(json.dumps(evidence, default=str))
