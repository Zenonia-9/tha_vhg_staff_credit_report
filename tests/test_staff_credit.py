import base64
import io
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestStaffCredit(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Staff Credit TEST Company',
                                                    'currency_id': cls.env.ref('base.USD').id})
        cls.env = cls.env(context=dict(cls.env.context, allowed_company_ids=[cls.company.id]))
        cls.account = cls.env['account.account'].create({'name': 'Staff TEST Receivable', 'code': '130100',
            'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(cls.company.ids)]})
        cls.salary = cls.env['account.account'].create({'name': 'Staff TEST Salary', 'code': '701010',
            'account_type': 'expense', 'company_ids': [Command.set(cls.company.ids)]})
        cls.journal = cls.env['account.journal'].create({'name': 'Staff TEST Journal', 'code': 'SCT',
                                                                       'type': 'general', 'company_id': cls.company.id})
        cls.config = cls.env['tha.staff.credit.config'].create({'company_id': cls.company.id,
            'account_id': cls.account.id, 'salary_account_id': cls.salary.id, 'journal_id': cls.journal.id})
        cls.department = cls.env['hr.department'].create({'name': 'Staff TEST Department', 'company_id': cls.company.id})
        cls.employee = cls.env['hr.employee'].create({'name': 'Staff TEST Employee', 'company_id': cls.company.id,
                                                     'department_id': cls.department.id})
        cls.partner = cls.employee.work_contact_id
        cls.reader = new_test_user(cls.env, login='staff_credit_test_reader',
            groups='base.group_user,tha_vhg_staff_credit_report.group_reader',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.manager = new_test_user(cls.env, login='staff_credit_test_manager',
            groups='base.group_user,tha_vhg_staff_credit_report.group_manager,account.group_account_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])

    def _source(self, amount=300, day='2026-08-31', credit=False):
        move = self.env['account.move'].create({'company_id': self.company.id, 'journal_id': self.journal.id,
            'date': day, 'ref': 'Staff Credit TEST source', 'line_ids': [
                Command.create({'account_id': self.account.id, 'partner_id': self.partner.id, 'date_maturity': day,
                                'credit' if credit else 'debit': amount}),
                Command.create({'account_id': self.salary.id, 'debit' if credit else 'credit': amount})]})
        move.action_post()
        return move.line_ids.filtered(lambda l: l.account_id == self.account)

    def _bill(self, amount=300, source=None, count=3, employee=None):
        line = source or self._source(amount)
        bill = self.env['tha.staff.credit'].create({'company_id': self.company.id,
            'employee_id': (employee or self.employee).id, 'department_id': self.department.id,
            'partner_id': self.partner.id, 'source_move_id': line.move_id.id, 'source_line_id': line.id,
            'charge_date': line.date, 'description': '=Patient TEST', 'amount': amount,
            'start_month': '2026-09-01', 'installment_count': count, 'anzer_reference': 'ANZER-TEST'})
        bill.action_generate_schedule()
        return bill

    def _operation(self, month='2026-09-01', **values):
        return self.env['tha.staff.credit.operation'].create(dict({'company_id': self.company.id, 'month': month}, **values))

    def _generate(self, month='2026-09-01'):
        action = self._operation(month).with_user(self.manager).action_generate()
        return self.env['account.move'].search(action['domain'])

    def _allocate(self, bill, amount, day='2026-08-31', source=None):
        return self.env['tha.staff.credit.allocation'].create({'credit_id': bill.id,
            'source_line_id': (source or self._source(amount, day, True)).id, 'amount': amount})

    def test_grouping_draft_post_and_duplicate(self):
        first, second = self._bill(300), self._bill(600)
        moves = self._generate()
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves.state, 'draft')
        self.assertEqual(moves.date, date(2026, 9, 30))
        self.assertEqual(len(moves.line_ids.filtered('tha_staff_credit_id')), 2)
        self.assertEqual(sum(moves.line_ids.mapped('debit')), 300)
        self.assertEqual(first._settled_at(), 0)
        self.assertEqual(self._generate(), moves)
        moves.action_post()
        self.assertEqual((first._settled_at(), second._settled_at()), (100, 200))
        self.assertEqual(self._generate(), moves)

    def test_staff_grouping(self):
        self._bill()
        employee = self.env['hr.employee'].create({'name': 'Other TEST Staff', 'company_id': self.company.id})
        self._bill(employee=employee)
        self.assertEqual(len(self._generate()), 2)

    def test_draft_delete_regenerate_and_lock(self):
        bill = self._bill()
        move = self._generate()
        first = bill.schedule_ids.sorted('due_date')[0]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            first.amount = 99
        with self.assertRaises(UserError), self.env.cr.savepoint():
            first.unlink()
        move.unlink()
        self.assertFalse(first.locked)
        regenerated = self._generate()
        self.assertNotEqual(regenerated.id, move.id)
        regenerated.action_post()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            regenerated.button_draft()

    def test_historical_report_plan_and_reversal(self):
        bill = self._bill()
        move = self._generate()
        september = self._operation()._rows()[0]
        self.assertEqual((september[6], september[7], september[8], september[9]), (0, '1/3', 100, 300))
        move.action_post()
        october = self._operation('2026-10-01')._rows()[0]
        self.assertEqual((october[6], october[7], october[8], october[9]), (100, '2/3', 100, 200))
        reverse = move._reverse_moves([{'date': '2026-11-30'}])
        reverse.action_post()
        self.assertEqual(bill._settled_at(), 0)
        self.assertEqual(self._operation('2026-10-01')._rows()[0], october)
        self.assertEqual(self._operation('2026-11-01')._rows()[0][9], 300)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            duplicate = move._reverse_moves([{'date': '2026-12-31'}])
            duplicate.action_post()

    def test_split_source_and_allocation_limits(self):
        source = self._source(300)
        first, second = self._bill(100, source), self._bill(200, source)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._bill(1, source)
        credit = self._source(100, credit=True)
        self._allocate(first, 50, source=credit)
        self._allocate(second, 50, source=credit)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            second.allocation_ids.amount = 51
        self.assertEqual(first._settled_at(), 50)

    def test_capacity_with_reserved_drafts_and_late_settlement(self):
        bill = self._bill(300, count=1)
        self._generate()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._allocate(bill, 1)
        self._generate().unlink()
        self._allocate(bill, 200)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._generate()

    def test_no_double_count_generated_credit(self):
        bill = self._bill()
        move = self._generate()
        move.action_post()
        line = move.line_ids.filtered('tha_staff_credit_id')
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._allocate(bill, 100, source=line)

    def test_rounding_skip_and_invalid_plan(self):
        bill = self._bill(100)
        self.assertEqual(bill.schedule_ids.mapped('amount'), [33.33, 33.33, 33.34])
        bill.schedule_ids.sorted('due_date')[1].due_date = '2026-12-31'
        self.assertEqual(self._operation('2026-10-01')._rows()[0][7:9], ['', 0])
        self.assertEqual(self._operation('2026-12-01')._rows()[0][7], '3/3')
        bill.schedule_ids.sorted('due_date')[0].amount = 20
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._generate()

    def test_source_protection_and_onchange(self):
        source = self._source()
        draft = self.env['tha.staff.credit'].new({'company_id': self.company.id, 'source_move_id': source.move_id.id})
        draft._onchange_move()
        self.assertEqual(draft.source_line_id, source)
        self.assertEqual(draft.amount, 300)
        bill = self._bill(source=source)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            source.move_id.button_draft()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            source.partner_id = False
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._bill(1, self._source(1, credit=True))
        self.assertEqual(bill.source_move_id, source.move_id)

    def test_permissions_and_company_scope(self):
        bill = self._bill()
        self.assertTrue(bill.with_user(self.reader).read(['description']))
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            bill.with_user(self.reader).remark = 'Forbidden'
        with self.assertRaises(AccessError):
            self.env['tha.staff.credit'].with_user(self.reader).action_settings()
        with self.assertRaises(AccessError):
            self._operation().with_user(self.reader).action_generate()
        other = self.env['res.company'].create({'name': 'Staff TEST Other Company'})
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self._operation(company_id=other.id).with_user(self.reader).action_export()
        operation = self._operation().with_user(self.manager)
        action = operation.action_generate()
        self.assertEqual(len(self.env['account.move'].search(action['domain'])), 1)

    def test_filters_and_export_structure(self):
        bill = self._bill()
        self._allocate(bill, 300)
        self.assertFalse(self._operation(status='open')._rows())
        operation = self._operation(status='settled')
        rows = operation._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][11:14], [bill.name, 'ANZER-TEST', bill.source_move_id.name])
        with zipfile.ZipFile(io.BytesIO(operation._xlsx())) as book:
            ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            strings = ET.fromstring(book.read('xl/sharedStrings.xml'))
            labels = [''.join(s.itertext()) for s in strings]
            self.assertIn('Settlement up to Sep\'26', labels)
            self.assertIn('Balance for Sep\'26', labels)
            self.assertEqual(len(sheet.findall("m:sheetData/m:row[@r='4']/m:c", ns)), 14)
            self.assertFalse(sheet.findall('.//m:f', ns))
            self.assertIsNotNone(sheet.find('m:sheetViews/m:sheetView/m:pane', ns))
            self.assertIn('FFBDD7EE', book.read('xl/styles.xml').decode())
        operation.action_export()
        self.assertTrue(base64.b64decode(operation.file_data).startswith(b'PK'))

    def test_only_one_menu(self):
        menus = self.env['ir.model.data'].search([('module', '=', 'tha_vhg_staff_credit_report'), ('model', '=', 'ir.ui.menu')])
        self.assertEqual(len(menus), 1)
        menu = self.env['ir.ui.menu'].browse(menus.res_id)
        self.assertEqual(menu.name, 'Staff Credit Report')
        self.assertEqual(menu.parent_id, self.env.ref('tha_vhg_daily_cash_register.menu_other_reports'))


    def test_tampered_draft_and_posted_link_changes(self):
        bill = self._bill()
        move = self._generate()
        line = move.line_ids.filtered('tha_staff_credit_id')
        with self.assertRaises(UserError), self.env.cr.savepoint():
            line.credit = 99
        # Salary changes remain subject to normal accounting editing, but an
        # inconsistent debit must never be posted as a Staff Credit deduction.
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            salary = move.line_ids - line
            salary.with_context(check_move_validity=False).debit = 99
            move.action_post()
        ordinary = self._source(10, credit=True)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            ordinary.write({'tha_staff_credit_id': bill.id, 'tha_staff_credit_schedule_id': bill.schedule_ids[0].id})

    def test_foreign_currency_and_wrong_company_staff(self):
        source = self._source()
        other = self.env['res.company'].create({'name': 'Staff TEST foreign company'})
        employee = self.env['hr.employee'].create({'name': 'Staff TEST foreign employee', 'company_id': other.id})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._bill(source=source, employee=employee)
        foreign = self.env.ref('base.EUR')
        foreign.active = True
        move = self.env['account.move'].create({'company_id': self.company.id, 'journal_id': self.journal.id,
            'date': '2026-08-31', 'line_ids': [
                Command.create({'account_id': self.account.id, 'partner_id': self.partner.id,
                    'debit': 300, 'currency_id': foreign.id, 'amount_currency': 300, 'date_maturity': '2026-08-31'}),
                Command.create({'account_id': self.salary.id, 'credit': 300})]})
        move.action_post()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._bill(source=move.line_ids.filtered(lambda l: l.account_id == self.account))

    def test_database_batch_uniqueness(self):
        from psycopg2 import IntegrityError
        self._bill()
        move = self._generate()
        batch = move.tha_staff_credit_batch_id
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['tha.staff.credit.batch'].create({'company_id': batch.company_id.id,
                'employee_id': batch.employee_id.id, 'month': batch.month})
            self.env.flush_all()

    def test_customer_invoice_link(self):
        revenue = self.env['account.account'].create({'name': 'Staff TEST Revenue', 'code': '400100',
            'account_type': 'income', 'company_ids': [Command.set(self.company.ids)]})
        self.partner.with_company(self.company).property_account_receivable_id = self.account
        sales = self.env['account.journal'].create({'name': 'Staff TEST Sales', 'code': 'SCS',
                                                  'type': 'sale', 'company_id': self.company.id})
        invoice = self.env['account.move'].create({'company_id': self.company.id, 'journal_id': sales.id,
            'move_type': 'out_invoice', 'invoice_date': '2026-08-31', 'partner_id': self.partner.id,
            'invoice_line_ids': [Command.create({'name': 'Staff TEST hospital bill', 'account_id': revenue.id,
                                                'quantity': 1, 'price_unit': 300, 'tax_ids': [Command.clear()]})]})
        invoice.action_post()
        bill = self._bill(source=invoice.line_ids.filtered(lambda l: l.account_id == self.account))
        self.assertEqual(bill.source_move_id, invoice)
        self.assertEqual(bill.amount, 300)
