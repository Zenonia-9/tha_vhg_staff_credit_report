{
    "name": "VHG Staff Credit Report",
    "version": "19.0.1.0.5",
    "summary": "Staff credit register, monthly deductions and GL reconciliation",
    "author": "Thein Htoo Aung",
    "license": "LGPL-3",
    "category": "Accounting/Accounting",
    "depends": ["account", "hr", "mail", "tha_vhg_daily_cash_register"],
    "external_dependencies": {"python": ["xlsxwriter"]},
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/staff_credit_views.xml",
        "wizard/report_views.xml",
        "wizard/import_views.xml",
        "report/staff_credit_report.xml",
    ],
    "installable": True,
}
