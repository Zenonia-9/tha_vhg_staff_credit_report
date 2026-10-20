from dateutil.relativedelta import relativedelta

from odoo import fields, models, _
from odoo.exceptions import AccessError

from .staff_credit import CATEGORIES


class StaffCreditReportHandler(models.AbstractModel):
    _name = "tha.staff.credit.report.handler"
    _inherit = "account.report.custom.handler"
    _description = "Native Monthly Staff Credit Report"

    def _check_staff_access(self):
        if not self.env.su and not self.env.user.has_group("tha_vhg_staff_credit_report.group_reader"):
            raise AccessError(_("Staff Credit Reader access is required to view this report."))

    def _company(self, report, options):
        self._check_staff_access()
        companies = self.env["res.company"].browse(report.get_report_company_ids(options))
        if any(company not in self.env.companies for company in companies):
            raise AccessError(_("The report company must be in your allowed companies."))
        return companies if len(companies) == 1 else self.env["res.company"]

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options)
        company = self._company(report, options)
        start = fields.Date.to_date(options["date"]["date_to"]).replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        date_filter = options["date"].get("filter", "custom")
        options["date"].update(report._get_dates_period(start, end, "range", period_type="month"))
        options["date"]["filter"] = date_filter
        for group in options["column_groups"].values():
            group["forced_options"]["date"] = dict(options["date"])
        previous_label = (start - relativedelta(days=1)).strftime("%b %Y")
        month_label = start.strftime("%b %Y")
        for column in options["columns"]:
            column["name"] = {
                "prior": _("Settled through %s", previous_label),
                "planned": _("%s Planned", month_label),
                "actual": _("%s Actual", month_label),
            }.get(column["expression_label"], column["name"])
        employees = self.env["hr.employee.public"].with_context(active_test=False).search([
            ("company_id", "in", company.ids)], order="name")
        departments = self.env["hr.department"].with_context(active_test=False).search([
            ("company_id", "in", company.ids)], order="name")
        choices = {
            "staff_credit_employee": [(employee.id, employee.name) for employee in employees],
            "staff_credit_department": [(department.id, department.name) for department in departments],
            "staff_credit_category": CATEGORIES,
            "staff_credit_status": [("open", _("Open at month end")), ("settled", _("Settled at month end"))],
        }
        for key, values in choices.items():
            selected = next((item.get("id") for item in previous_options.get(key, []) if item.get("selected")), None)
            options[key] = [{"id": value, "name": name, "selected": value == selected} for value, name in values]
        if not company:
            notice = _("Select one company to view its staff credit and GL reconciliation.")
        elif not self.env["tha.staff.credit.config"].search_count([("company_id", "=", company.id)]):
            notice = _("No Staff Credit account configured for %s. Select the hospital company to see the local examples, or configure an account in Staff Credit > Accounts.", company.name)
        else:
            notice = ""
        options["staff_credit_notice"] = notice
        options["custom_display_config"].update({
            "templates": {"AccountReportFilters": "tha_vhg_staff_credit_report.NativeFilters"},
            "components": {"AccountReportFilters": "StaffCreditFilters"},
            "css_custom_class": "tha_staff_credit_native",
            "pdf_export": {"pdf_export_main": "tha_vhg_staff_credit_report.native_pdf_layout"},
        })
        options["buttons"].append({"name": _("Register"), "sequence": 30, "action": "open_staff_credit_register",
                                    "action_type": "object", "always_show": True})

    def _selected(self, options, key):
        return next((item["id"] for item in options.get(key, []) if item.get("selected")), False)

    def _data(self, report, options):
        company = self._company(report, options)
        if not company or not self.env["tha.staff.credit.config"].search_count([("company_id", "=", company.id)]):
            return None
        employee_id = self._selected(options, "staff_credit_employee")
        department_id = self._selected(options, "staff_credit_department")
        if employee_id and not self.env["hr.employee.public"].with_context(active_test=False).search_count([
                ("id", "=", employee_id), ("company_id", "=", company.id)]):
            raise AccessError(_("Employee does not belong to the report company."))
        if department_id and not self.env["hr.department"].with_context(active_test=False).search_count([
                ("id", "=", department_id), ("company_id", "=", company.id)]):
            raise AccessError(_("Department does not belong to the report company."))
        # Reuse the accounting calculations without saving a transient report/preview.
        wizard = self.env["tha.staff.credit.report"].new({
            "company_id": company.id, "month": options["date"]["date_to"],
            "employee_id": employee_id, "department_id": department_id,
            "category": self._selected(options, "staff_credit_category"),
            "status": self._selected(options, "staff_credit_status") or "all",
        })
        data = wizard._data()
        search = (options.get("filter_search_bar") or "").strip().casefold()
        if search:
            data["rows"] = [row for row in data["rows"] if search in " ".join(
                str(row[key]) for key in ("name", "staff", "department", "description", "remark", "reference")).casefold()]
        return data

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        data = self._data(report, options)
        company = self._company(report, options)
        currency = company.currency_id if company else self.env.company.currency_id
        result = []

        def line(name, values=None, model=None, record_id=None, markup=None, parent=None, total=False, section=False):
            values = values or {}
            row = {
                "id": report._get_generic_line_id(model, record_id, markup=markup, parent_line_id=parent),
                "name": name, "level": 1 if parent else 0,
                "columns": [report._build_column_dict(values.get(column["expression_label"]), column,
                    options=options, currency=currency if column["figure_type"] == "monetary" else False)
                    for column in options["columns"]],
            }
            if parent:
                row["parent_id"] = parent
            if total:
                row["class"] = "fw-bold"
            if section:
                row["colspan"] = len(options["columns"]) + 1
                row["columns"] = []
            if model == "tha.staff.credit":
                row["caret_options"] = "tha.staff.credit"
            elif model == "account.move.line":
                row["caret_options"] = "account.move.line"
            result.append((len(result), row))
            return row["id"]

        if not data:
            line(options.get("staff_credit_notice", _("Select a configured company.")), markup="staff_credit_notice", section=True)
            return result
        header = line(_("Staff Credit — %s", company.name), markup="staff_credit_charges", total=True, section=True)
        for row in data["rows"]:
            line(row["name"], row, "tha.staff.credit", row["credit_id"], parent=header)
        if not data["rows"]:
            line(_("No staff charges match this month and these filters."), markup="staff_credit_empty", parent=header, section=True)
        line(_("Filtered totals"), {key: sum(row[key] for row in data["rows"]) for key in
             ("amount", "prior", "balance", "planned", "actual", "closing")}, markup="staff_credit_totals", total=True)
        reconciliation = line(_("Company-wide GL reconciliation (independent of staff filters)"),
                              markup="staff_credit_reconciliation", total=True, section=True)
        for key, label in (
            ("opening", _("Opening balance")), ("charges", _("New charges during month")),
            ("reductions", _("Reductions during month")), ("closing", _("Closing balance")),
            ("gl_balance", _("Posted GL balance")), ("difference", _("GL difference")),
            ("unlinked_debits", _("Unlinked debits")), ("unapplied_credits", _("Unapplied credits")),
        ):
            line(label, {"gl_amount": data["summary"][key]}, markup="staff_credit_" + key, parent=reconciliation,
                 total=key in ("closing", "difference"))
        for row in data["audit"]:
            line(_("Unallocated: %s", row["reference"]), {
                "date": row["date"], "staff": row["partner"], "reference": row["reference"],
                "remark": _("Unlinked debit: %(debit)s; unapplied credit: %(credit)s", debit=row["debit"], credit=row["credit"]),
                "gl_amount": row["debit"] - row["credit"],
            }, "account.move.line", row["source_line_id"], parent=reconciliation)
        return result

    def _caret_options_initializer(self):
        options = super()._caret_options_initializer()
        options["tha.staff.credit"] = [
            {"name": _("Open Staff Credit"), "action": "open_staff_credit"},
            {"name": _("View charge journal entry"), "action": "open_staff_credit_source"},
        ]
        return options

    def export_to_pdf(self, options):
        """Keep the native PDF renderer/toolbar, using A3 for this wide register."""
        report = self.env["account.report"].browse(options["report_id"])
        company = self._company(report, options)
        if company:
            report = report.with_company(company)
        print_options = report.get_options(dict(options, export_mode="print"))
        parameters = self.env["ir.config_parameter"].sudo()
        base_url = parameters.get_param("report.url") or parameters.get_param("web.base.url")
        body = report._get_pdf_export_html(print_options, report._get_lines(print_options),
                                          additional_context={"base_url": base_url})
        footer = report._get_layout_footer({"mode": "print", "base_url": base_url, "company": report.env.company})
        content = self.env["ir.actions.report"]._run_wkhtmltopdf(
            [body], report_ref="tha_vhg_staff_credit_report.action_report_pdf", footer=footer, landscape=True)
        return {"file_name": report.get_default_report_filename(options, "pdf"),
                "file_content": content, "file_type": "pdf"}

    def _credit_from_line(self, options, params):
        self._check_staff_access()
        report = self.env["account.report"].browse(options["report_id"])
        model, record_id = report._get_model_info_from_id(params["line_id"])
        if model != "tha.staff.credit":
            raise AccessError(_("Choose a staff credit charge row."))
        credit = self.env[model].browse(record_id)
        credit.check_access("read")
        if credit.company_id != self._company(report, options):
            raise AccessError(_("Charge does not belong to the report company."))
        return credit

    def open_staff_credit(self, options, params):
        credit = self._credit_from_line(options, params)
        return {"type": "ir.actions.act_window", "res_model": credit._name, "res_id": credit.id,
                "views": [(False, "form")], "target": "current"}

    def open_staff_credit_source(self, options, params):
        credit = self._credit_from_line(options, params)
        return {"type": "ir.actions.act_window", "res_model": "account.move", "res_id": credit.source_move_id.id,
                "views": [(False, "form")], "target": "current"}

    def open_staff_credit_register(self, options):
        report = self.env["account.report"].browse(options["report_id"])
        company = self._company(report, options)
        action = self.env["ir.actions.actions"]._for_xml_id("tha_vhg_staff_credit_report.action_credit")
        action["domain"] = [("company_id", "in", company.ids)]
        return action
