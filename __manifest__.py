{
    "name": "VHG Staff Credit Report",
    "version": "19.0.1.1.2",
    "summary": "Staff credit register, monthly deductions and GL reconciliation",
    "author": "Thein Htoo Aung",
    "license": "LGPL-3",
    "category": "Accounting/Accounting",
    "depends": ["account", "account_reports", "hr", "mail", "tha_vhg_daily_cash_register"],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/staff_credit_views.xml",
        "wizard/report_views.xml",
        "wizard/import_views.xml",
        "report/staff_credit_report.xml",
        "data/native_report.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tha_vhg_staff_credit_report/static/src/native_report.js",
            "tha_vhg_staff_credit_report/static/src/native_report.xml",
            "tha_vhg_staff_credit_report/static/src/native_report.scss",
        ],
        "account_reports.assets_pdf_export": ["tha_vhg_staff_credit_report/static/src/native_report.scss"],
    },
    "installable": True,
}
