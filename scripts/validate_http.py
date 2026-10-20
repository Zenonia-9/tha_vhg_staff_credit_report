"""Exercise report endpoints as an ordinary logged-in user, not shell superuser.

Run after seed_local_demo.py. Set ODOO_TEST_URL, ODOO_TEST_LOGIN and
ODOO_TEST_PASSWORD in the process environment; credentials are never printed.
"""
import io
import json
import os
import zipfile

import requests
from lxml import etree


url = os.environ.get("ODOO_TEST_URL", "http://localhost:8069").rstrip("/")
session = requests.Session()
response = session.post(url + "/web/session/authenticate", json={"jsonrpc": "2.0", "method": "call", "params": {
    "db": "THA", "login": os.environ["ODOO_TEST_LOGIN"], "password": os.environ["ODOO_TEST_PASSWORD"],
}}, timeout=60)
response.raise_for_status()
auth = response.json()
assert "error" not in auth and auth["result"].get("uid"), "Login failed"


def call(model, method, args=None, **kwargs):
    result = session.post(url + "/web/dataset/call_kw/" + model + "/" + method,
        json={"jsonrpc": "2.0", "method": "call", "params": {
            "model": model, "method": method, "args": args or [], "kwargs": kwargs,
        }}, timeout=90)
    result.raise_for_status()
    payload = result.json()
    if "error" in payload:
        raise AssertionError(payload["error"].get("data", {}).get("message", "RPC failed"))
    return payload["result"]


company_ids = call("res.company", "search", [[("name", "=", "THUKHA SAYTANAR CO. Ltd (Victoria Hospital)")]])
assert len(company_ids) == 1
context = {"allowed_company_ids": company_ids}
assert call("res.users", "has_group", [[auth["result"]["uid"]], "tha_vhg_staff_credit_report.group_manager"])
for model in ("tha.staff.credit", "tha.staff.credit.report", "tha.staff.credit.import"):
    views = call(model, "get_views", [], views=[[False, "form"]], options={}, context=context)
    assert views["views"]["form"]["arch"], model
employee = call("hr.employee.public", "search", [[("name", "=", "DEMO Staff Credit Employee"),
                                                           ("company_id", "in", company_ids)]], context=context)
assert len(employee) == 1
report = call("tha.staff.credit.report", "create", [{"company_id": company_ids[0], "month": "2026-10-01",
                                                     "employee_id": employee[0]}], context=context)
call("tha.staff.credit.report", "action_preview", [[report]], context=context)
snapshot = call("tha.staff.credit.report", "read", [[report], ["line_ids", "difference", "closing", "gl_balance",
                                                              "unlinked_debits", "unapplied_credits"]], context=context)[0]
assert len(snapshot["line_ids"]) == 2 and snapshot["difference"] == 0
assert snapshot["closing"] == snapshot["gl_balance"] == 513333
assert snapshot["unlinked_debits"] == snapshot["unapplied_credits"] == 0
action = call("tha.staff.credit.report", "action_excel", [[report]], context=context)
download = session.get(url + action["url"], timeout=60)
download.raise_for_status()
with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
    sheet = etree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert sheet.xpath("string(//s:c[@r='F5']/s:v)", namespaces=ns) == "470000"
    assert sheet.xpath("string(//s:c[@r='H5']/s:v)", namespaces=ns) == "313333"
call("tha.staff.credit.report", "action_pdf", [[report]], context=context)
pdf = session.get(url + "/report/pdf/tha_vhg_staff_credit_report.monthly_pdf/" + str(report),
                  params={"context": json.dumps(context)}, timeout=90)
pdf.raise_for_status()
assert pdf.content.startswith(b"%PDF"), "Report endpoint did not return PDF"
native_ids = call("account.report", "search", [[("custom_handler_model_name", "=", "tha.staff.credit.report.handler")]], context=context)
assert len(native_ids) == 1
native_id = native_ids[0]
native_options = call("account.report", "get_options", [[native_id], {
    "date": {"date_from": "2026-10-01", "date_to": "2026-10-31", "mode": "range", "filter": "custom"},
}], context=context)
native_info = call("account.report", "get_report_information", [[native_id], native_options], context=context)
native_rows = [line for line in native_info["lines"] if line.get("caret_options") == "tha.staff.credit"]
assert len(native_rows) == 3
for choice in native_options["staff_credit_status"]:
    choice["selected"] = choice["id"] == "settled"
settled_options = call("account.report", "get_options", [[native_id], native_options], context=context)
settled_info = call("account.report", "get_report_information", [[native_id], settled_options], context=context)
settled_rows = [line for line in settled_info["lines"] if line.get("caret_options") == "tha.staff.credit"]
assert len(settled_rows) == 1
assert next(cell["no_format"] for cell in settled_rows[0]["columns"] if cell.get("expression_label") == "times") == "2/2"
for choice in native_options["staff_credit_status"]:
    choice["selected"] = False
for kind, signature in (("pdf", b"%PDF"), ("xlsx", b"PK")):
    exported = session.post(url + "/account_reports", data={"options": json.dumps(native_options),
        "file_generator": "export_to_" + kind}, timeout=90)
    exported.raise_for_status()
    assert exported.content.startswith(signature), "Native download failed: " + kind
print(json.dumps({"authenticated_user_id": auth["result"]["uid"], "report_id": report,
                  "forms": "register/report/import loaded", "snapshot": snapshot,
                  "excel_bytes": len(download.content), "pdf_bytes": len(pdf.content),
                  "native_report_id": native_id, "native_rows": len(native_rows),
                  "native_settled_rows": len(settled_rows), "native_downloads": "PDF and XLSX passed"}))
