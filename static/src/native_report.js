/** @odoo-module **/

import { AccountReport } from "@account_reports/components/account_report/account_report";
import { AccountReportFilters } from "@account_reports/components/account_report/filters/filters";
import { _t } from "@web/core/l10n/translation";

export class StaffCreditFilters extends AccountReportFilters {
    creditFilterLabel(key, fallback) {
        return this.controller.cachedFilterOptions[key]?.find((item) => item.selected)?.name || fallback;
    }

    selectCreditFilter(key, value) {
        for (const item of this.controller.cachedFilterOptions[key]) {
            item.selected = item.id === value;
        }
        this.applyFilters(key);
    }

    get creditFilterDefinitions() {
        return [
            { key: "staff_credit_employee", label: _t("All Staff"), icon: "fa-user" },
            { key: "staff_credit_department", label: _t("All Departments"), icon: "fa-building-o" },
            { key: "staff_credit_category", label: _t("All Categories"), icon: "fa-tags" },
            { key: "staff_credit_status", label: _t("All Statuses"), icon: "fa-check-circle-o" },
        ];
    }
}

AccountReport.registerCustomComponent(StaffCreditFilters);
