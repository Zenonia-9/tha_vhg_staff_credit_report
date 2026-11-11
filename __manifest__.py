{
    'name': 'VHG Staff Credit Report',
    'version': '19.0.2.0.37',
    'summary': 'Linked staff bills, monthly deduction drafts and Excel reporting',
    'author': 'Thein Htoo Aung',
    'license': 'LGPL-3',
    'category': 'Accounting/Accounting',
    'depends': ['account', 'hr', 'mail', 'tha_vhg_daily_cash_register'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': ['security/security.xml', 'security/ir.model.access.csv',
             'wizard/operation_views.xml', 'views/staff_credit_views.xml'],
    'installable': True,
}
