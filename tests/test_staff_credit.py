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
        cls.invoice_credit = cls.env['account.account'].create({'name': 'Staff TEST Invoice Income', 'code': '510585',
            'account_type': 'income', 'company_ids': [Command.set(cls.company.ids)]})
        cls.journal = cls.env['account.journal'].create({'name': 'Staff TEST Journal', 'code': 'SCT',
                                                                       'type': 'general', 'company_id': cls.company.id})
        cls.sales_journal = cls.env['account.journal'].create({'name': 'Staff TEST Sales', 'code': 'SCS',
                                                               'type': 'sale', 'company_id': cls.company.id})
        cls.config = cls.env['tha.staff.credit.config'].create({'company_id': cls.company.id,
            'account_id': cls.account.id, 'salary_account_id': cls.salary.id,
            'invoice_credit_account_id': cls.invoice_credit.id, 'journal_id': cls.journal.id})
        cls.department = cls.env['hr.department'].create({'name': 'Staff TEST Department', 'company_id': cls.company.id})
        cls.employee = cls.env['hr.employee'].create({'name': 'Staff TEST Employee', 'company_id': cls.company.id,
                                                     'department_id': cls.department.id})
        cls.partner = cls.employee.work_contact_id
        cls.partner.with_company(cls.company).property_account_receivable_id = cls.account
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

    def _pending_bill(self, amount=300):
        return self.env['tha.staff.credit'].create({'company_id': self.company.id,
            'employee_id': self.employee.id, 'department_id': self.department.id, 'partner_id': self.partner.id,
            'charge_date': '2026-08-31', 'description': 'Staff Credit invoice test', 'amount': amount,
            'start_month': '2026-09-01', 'installment_count': 3})

    def test_original_invoice_draft_post_and_cancel_stage(self):
        bill = self._pending_bill()
        self.assertEqual(bill.state, 'draft')
        self.assertEqual((bill.settled_amount, bill.balance), (0, 0))
        action = bill.with_user(self.manager).action_create_original_invoice()
        invoice = self.env['account.move'].browse(action['res_id'])
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(invoice.tha_staff_credit_id, bill)
        self.assertEqual(invoice.move_type, 'out_invoice')
        self.assertEqual(invoice.invoice_date, bill.charge_date)
        self.assertEqual(invoice.invoice_line_ids.account_id, self.invoice_credit)
        term = invoice.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        self.assertEqual(len(term), 1)
        self.assertEqual(term.account_id, self.account)
        self.assertEqual(term.debit, bill.amount)
        self.assertEqual(invoice.invoice_line_ids.tax_ids, self.env['account.tax'])
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            invoice.invoice_line_ids.account_id = self.salary
            invoice.action_post()
        self.assertEqual(invoice.state, 'draft')
        export = self.env['tha.staff.credit.operation'].create({'company_id': self.company.id, 'mode': 'export'})
        self.assertNotIn(bill, export._bills())
        with self.assertRaises(UserError):
            self._operation().with_user(self.manager).action_generate()
        invoice.action_post()
        bill.invalidate_recordset()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(bill.source_move_id, invoice)
        self.assertEqual(bill.source_line_id.account_id, self.account)
        self.assertEqual(bill.source_line_id.debit, bill.amount)
        self.assertEqual(self.env['tha.staff.credit'].search_count([('invoice_id', '=', invoice.id)]), 1)
        self.assertIn(bill, export._bills())

    def test_cancelled_original_invoice_marks_staff_credit_cancelled(self):
        bill = self._pending_bill()
        invoice = self.env['account.move'].browse(
            bill.with_user(self.manager).action_create_original_invoice()['res_id'])
        invoice.button_cancel()
        bill.invalidate_recordset()
        self.assertEqual(bill.state, 'cancel')

    def _operation(self, month='2026-09-01', **values):
        values.setdefault('bill_ids', [Command.set(self.env['tha.staff.credit'].search([
            ('company_id', '=', values.get('company_id', self.company.id))]).ids)])
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
        self.assertEqual((september[6], september[7], september[8], september[9]), (0, '0/3', 100, 300))
        move.action_post()
        october = self._operation('2026-10-01')._rows()[0]
        self.assertEqual((october[6], october[7], october[8], october[9]), (100, '1/3', 100, 200))
        reverse = move._reverse_moves([{'date': '2026-11-30'}])
        reverse.action_post()
        self.assertEqual(bill._settled_at(), 0)
        self.assertEqual(self._operation('2026-10-01')._rows()[0], october)
        self.assertEqual(self._operation('2026-11-01')._rows()[0][9], 300)
        self.assertEqual(self._operation('2026-11-01')._rows()[0][7], '0/3')
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

    def test_times_completed_total_and_manual_partial_installments(self):
        bill = self._bill(500, count=5)
        self._allocate(bill, 250, day='2026-09-30')
        self._allocate(bill, 50, day='2026-10-31')
        self.assertEqual(self._operation('2026-09-01')._rows()[0][7], '2/5')
        self.assertEqual(self._operation('2026-10-01')._rows()[0][7], '3/5')
        self.assertEqual(self._operation('2027-03-01')._rows()[0][7:9], ['3/5', 0])
        self.assertEqual(self._operation(month=False)._rows()[0][7], '3/5')
        self._allocate(bill, 200, day='2026-11-30')
        self.assertEqual(self._operation('2026-11-01')._rows()[0][7], '5/5')
        self.assertEqual(self._operation('2026-10-01')._rows()[0][7], '3/5')

    def test_times_uses_actual_unequal_plan_and_rounding(self):
        bill = self._bill(100)
        plan = bill.schedule_ids.sorted('due_date')
        plan[0].amount = 20
        plan[1].amount = 30
        plan[2].amount = 50
        self._allocate(bill, 49.99, day='2026-09-30')
        self.assertEqual(self._operation()._rows()[0][7], '1/3')
        self._allocate(bill, 0.01, day='2026-10-31')
        self.assertEqual(self._operation('2026-10-01')._rows()[0][7], '2/3')
        self._allocate(bill, 50, day='2026-11-30')
        self.assertEqual(self._operation('2026-11-01')._rows()[0][7], '3/3')

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
        self.assertEqual(self._operation('2026-10-01')._rows()[0][7:9], ['0/3', 0])
        self.assertEqual(self._operation('2026-12-01')._rows()[0][7], '0/3')
        bill.schedule_ids.sorted('due_date')[0].amount = 20
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._generate()

    def test_source_protection_and_onchange(self):
        source = self._source()
        draft = self.env['tha.staff.credit'].new({'company_id': self.company.id, 'source_move_id': source.move_id.id})
        draft._onchange_move()
        self.assertEqual(draft.source_line_id, source)
        self.assertFalse(draft.source_line_selection_required)
        self.assertEqual(draft.amount, 300)
        bill = self._bill(source=source)
        self.assertFalse(bill.with_user(self.reader).source_line_selection_required)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            source.move_id.button_draft()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            source.partner_id = False
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._bill(1, self._source(1, credit=True))
        self.assertEqual(bill.source_move_id, source.move_id)

    def test_source_debit_choice_only_for_ambiguous_documents(self):
        draft = self.env['tha.staff.credit'].new({'company_id': self.company.id})
        self.assertFalse(draft.source_line_selection_required)
        move = self.env['account.move'].create({'company_id': self.company.id,
            'journal_id': self.journal.id, 'date': '2026-08-31', 'line_ids': [
                Command.create({'account_id': self.account.id, 'partner_id': self.partner.id,
                    'date_maturity': '2026-08-31', 'debit': 100}),
                Command.create({'account_id': self.account.id, 'partner_id': self.partner.id,
                    'date_maturity': '2026-08-31', 'debit': 200}),
                Command.create({'account_id': self.salary.id, 'credit': 300})]})
        move.action_post()
        draft.source_move_id = move
        draft._onchange_move()
        self.assertTrue(draft.source_line_selection_required)
        self.assertFalse(draft.source_line_id)
        draft.source_line_id = move.line_ids.filtered(lambda line: line.debit == 200)
        draft._onchange_source()
        self.assertEqual(draft.amount, 200)
        self.assertTrue(draft.source_line_selection_required)
        from lxml import etree
        arch = etree.fromstring(self.env.ref('tha_vhg_staff_credit_report.view_credit_form').arch_db)
        field = arch.xpath('//field[@name="source_line_id"]')[0]
        self.assertEqual(field.get('invisible'), 'not source_line_selection_required')
        self.assertEqual(field.get('force_save'), '1')

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
            self.assertIn('Posted through\n30 Sep 2026', labels)
            self.assertIn('Balance\nas at 30 Sep 2026', labels)
            self.assertEqual(len(sheet.findall('m:mergeCells/m:mergeCell', ns)), 15)
            self.assertEqual(len(sheet.findall("m:sheetData/m:row[@r='6']/m:c", ns)), 14)
            self.assertEqual(len(sheet.findall("m:sheetData/m:row[@r='7']/m:c", ns)), 14)
            self.assertFalse(sheet.findall('.//m:f', ns))
            self.assertIsNotNone(sheet.find('m:sheetViews/m:sheetView/m:pane', ns))
            self.assertIn('FF17365D', book.read('xl/styles.xml').decode())
            self.assertIn('FFE2F0D9', book.read('xl/styles.xml').decode())
        self.assertEqual(operation.action_export()['target'], 'download')
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
        sales = self.sales_journal
        invoice = self.env['account.move'].create({'company_id': self.company.id, 'journal_id': sales.id,
            'move_type': 'out_invoice', 'invoice_date': '2026-08-31', 'partner_id': self.partner.id,
            'invoice_line_ids': [Command.create({'name': 'Staff TEST hospital bill', 'account_id': revenue.id,
                                                'quantity': 1, 'price_unit': 300, 'tax_ids': [Command.clear()]})]})
        invoice.action_post()
        bill = self._bill(source=invoice.line_ids.filtered(lambda l: l.account_id == self.account))
        self.assertEqual(bill.source_move_id, invoice)
        self.assertEqual(bill.amount, 300)

    def test_xml_development_loader_all_views(self):
        from odoo.addons.base.models.ir_ui_view import get_view_arch_from_file
        from odoo.tools import file_path
        from lxml import etree

        # Production uses --dev=xml: it reads the source architecture rather
        # than only the stored database arch. Include the search view, too.
        for xmlid in ('view_credit_list', 'view_credit_form', 'view_credit_search',
                      'view_config_form', 'view_operation'):
            with self.subTest(view=xmlid):
                view = self.env.ref('tha_vhg_staff_credit_report.' + xmlid)
                arch = get_view_arch_from_file(file_path(view.arch_fs),
                                              'tha_vhg_staff_credit_report.' + xmlid)
                self.assertIsNotNone(etree.fromstring(arch))
        for model, types in [('tha.staff.credit', ['list', 'form', 'search']),
                             ('tha.staff.credit.config', ['form']),
                             ('tha.staff.credit.operation', ['form']),
                             ('tha.staff.credit.settings.wizard', ['form'])]:
            result = self.env[model].with_user(self.manager).get_views(
                [(False, kind) for kind in types], {'toolbar': True})
            self.assertEqual(set(result['views']), set(types))

    def test_settings_button_opens_bill_scoped_override(self):
        bill = self._bill()
        action = bill.with_user(self.manager).action_settings()
        self.assertEqual(action['res_model'], 'tha.staff.credit.settings.wizard')
        self.assertEqual(action['context']['default_credit_id'], bill.id)
        wizard = self.env['tha.staff.credit.settings.wizard'].with_user(self.manager).create({
            'company_id': self.company.id, 'credit_id': bill.id,
            'account_id': self.account.id, 'salary_account_id': self.salary.id,
            'journal_id': self.journal.id, 'save_as_default': False})
        wizard.action_apply()
        self.assertEqual(self.config.journal_id, self.journal)
        with self.assertRaises(AccessError):
            self.env['tha.staff.credit'].with_user(self.reader).action_settings()

    def test_invoice_credit_account_default_and_validation(self):
        defaults = self.env['tha.staff.credit.config'].with_company(self.company).default_get(
            ['company_id', 'invoice_credit_account_id'])
        self.assertEqual(defaults['invoice_credit_account_id'], self.invoice_credit.id)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.config.write({'invoice_credit_account_id': self.account.id})
        other = self.env['res.company'].create({'name': 'Staff Credit invoice account company',
                                                'currency_id': self.company.currency_id.id})
        other_income = self.env['account.account'].create({'name': 'Other Income', 'code': '510585',
            'account_type': 'income', 'company_ids': [Command.set(other.ids)]})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.config.write({'invoice_credit_account_id': other_income.id})
        bill = self._pending_bill()
        with self.assertRaises(UserError):
            self.config.invoice_credit_account_id = False
            bill.with_user(self.manager).action_create_original_invoice()

    def test_list_settings_empty_single_and_multiple_selection(self):
        model = self.env['tha.staff.credit'].with_user(self.manager)
        action = model.action_settings()
        self.assertEqual(action['res_model'], 'tha.staff.credit.config')
        self.assertEqual(action['res_id'], self.config.id)
        self.assertEqual(action['context']['default_company_id'], self.company.id)
        first, second = self._bill(), self._bill()
        for bills in (first, first | second):
            action = bills.with_user(self.manager).with_context(
                tha_staff_credit_company_settings=True).action_settings()
            self.assertEqual(action['res_model'], 'tha.staff.credit.config')
            self.assertEqual(action['res_id'], self.config.id)
        from lxml import etree
        arch = etree.fromstring(self.env.ref('tha_vhg_staff_credit_report.view_credit_list').arch_db)
        button = arch.xpath('//header/button[@name="action_settings"]')[0]
        self.assertIn('tha_staff_credit_company_settings', button.get('context'))
        with self.assertRaises(AccessError):
            model.with_user(self.reader).with_context(tha_staff_credit_company_settings=True).action_settings()

    def test_list_settings_first_time_setup_does_not_create_config(self):
        company = self.env['res.company'].create({'name': 'Unconfigured Staff Credit Company'})
        self.manager.write({'company_ids': [Command.link(company.id)]})
        model = self.env['tha.staff.credit'].with_user(self.manager).with_company(company)
        action = model.action_settings()
        self.assertEqual(action['res_model'], 'tha.staff.credit.config')
        self.assertFalse(action['res_id'])
        self.assertEqual(action['context']['default_company_id'], company.id)
        self.assertFalse(self.env['tha.staff.credit.config'].search([('company_id', '=', company.id)]))

    def test_export_form_defaults_follow_active_bill(self):
        bill = self._bill()
        operation = self.env['tha.staff.credit.operation'].with_user(self.manager).with_context(
            default_mode='export', active_model='tha.staff.credit', active_id=bill.id,
            tha_from_credit_form=True).default_get(
                ['mode', 'company_id', 'employee_id', 'department_id', 'category'])
        self.assertEqual(operation['employee_id'], bill.employee_id.id)
        self.assertEqual(operation['department_id'], bill.department_id.id)
        self.assertEqual(operation['category'], bill.category)

    def test_export_selected_bills_and_company_wide(self):
        first, second = self._bill(300), self._bill(600)
        selected = self._operation(mode='export', bill_ids=[Command.set(first.ids)])
        self.assertEqual(selected._bills(), first)
        all_bills = self._operation(mode='export', bill_ids=[Command.clear()])
        self.assertEqual(set(all_bills._bills().ids), set((first | second).ids))
        form = self.env['tha.staff.credit.operation'].with_context(default_mode='export',
            active_model='tha.staff.credit', active_id=second.id, tha_from_credit_form=True).create({})
        self.assertEqual(form._bills(), second)

    def test_company_numbering_and_legacy_seed(self):
        first, second = self._bill(), self._bill()
        prefix = 'SC/%s/' % self.company.id
        self.assertEqual(first.name, prefix + '000001')
        self.assertEqual(second.name, prefix + '000002')
        other = self.env['res.company'].create({'name': 'Independent Staff Credit Company',
                                               'currency_id': self.company.currency_id.id})
        other_env = self.env(context=dict(self.env.context, allowed_company_ids=other.ids))
        account = other_env['account.account'].create({'name': 'Receivable', 'code': '130100',
            'account_type': 'asset_receivable', 'reconcile': True, 'company_ids': [Command.set(other.ids)]})
        salary = other_env['account.account'].create({'name': 'Salary', 'code': '701010',
            'account_type': 'expense', 'company_ids': [Command.set(other.ids)]})
        journal = other_env['account.journal'].create({'name': 'Staff Credit', 'code': 'SCT',
                                                       'type': 'general', 'company_id': other.id})
        revenue = other_env['account.account'].create({'name': 'Income', 'code': '510585',
            'account_type': 'income', 'company_ids': [Command.set(other.ids)]})
        other_env['tha.staff.credit.config'].create({'company_id': other.id, 'account_id': account.id,
            'salary_account_id': salary.id, 'invoice_credit_account_id': revenue.id, 'journal_id': journal.id})
        department = other_env['hr.department'].create({'name': 'Finance', 'company_id': other.id})
        employee = other_env['hr.employee'].create({'name': 'Other Staff', 'company_id': other.id,
                                                    'department_id': department.id})
        source = other_env['account.move'].create({'company_id': other.id, 'journal_id': journal.id,
            'date': '2026-08-31', 'line_ids': [Command.create({'account_id': account.id,
                'partner_id': employee.work_contact_id.id, 'date_maturity': '2026-08-31', 'debit': 300}),
                Command.create({'account_id': salary.id, 'credit': 300})]})
        source.action_post()
        bill = other_env['tha.staff.credit'].create({'company_id': other.id, 'employee_id': employee.id,
            'department_id': department.id, 'partner_id': employee.work_contact_id.id,
            'source_move_id': source.id, 'source_line_id': source.line_ids.filtered(lambda l: l.debit).id,
            'charge_date': '2026-08-31', 'description': 'Independent numbering', 'amount': 300,
            'start_month': '2026-09-01', 'installment_count': 3})
        self.assertEqual(bill.name, 'SC/%s/000001' % other.id)
        sequence = self.env['ir.sequence'].search([('code', '=', 'tha.staff.credit'),
                                                  ('company_id', '=', self.company.id)])
        sequence.unlink()
        second.name = prefix + '000050'
        self.assertEqual(self._bill().name, prefix + '000051')

    def test_selected_bills_only_and_incremental_staff_draft(self):
        first, second = self._bill(300), self._bill(600)
        operation = self._operation(bill_ids=[Command.set(first.ids)]).with_user(self.manager)
        move = self.env['account.move'].search(operation.action_generate()['domain'])
        self.assertEqual(move.line_ids.tha_staff_credit_id, first)
        self.assertEqual(sum(move.line_ids.mapped('debit')), 100)
        operation.bill_ids = first | second
        merged = self.env['account.move'].search(operation.action_generate()['domain'])
        self.assertEqual(merged, move)
        self.assertEqual(merged.line_ids.tha_staff_credit_id, first | second)
        self.assertEqual(sum(merged.line_ids.mapped('debit')), 300)
        operation.action_generate()
        self.assertEqual(len(move.line_ids), 3)
        move.action_post()
        self.assertEqual((first._settled_at(), second._settled_at()), (100, 200))

    def test_selected_single_bill_can_post_without_other_staff_bills(self):
        first = self._bill(300)
        second = self._bill(600)
        operation = self._operation(bill_ids=[Command.set(first.ids)]).with_user(self.manager)
        move = self.env['account.move'].search(operation.action_generate()['domain'])
        move.action_post()
        self.assertEqual(second._settled_at(), 0)
        operation.bill_ids = second
        with self.assertRaises(UserError), self.env.cr.savepoint():
            operation.action_generate()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self._operation(bill_ids=[Command.clear()]).with_user(self.manager).action_generate()

    def test_form_and_list_selection_context(self):
        first, second = self._bill(), self._bill()
        model = self.env['tha.staff.credit.operation'].with_context(
            default_mode='deductions', active_model='tha.staff.credit', active_ids=first.ids)
        wizard = model.create({'month': '2026-09-01'})
        self.assertEqual(wizard.bill_ids, first)
        wizard = model.with_context(active_ids=(first | second).ids).create({'month': '2026-09-01'})
        self.assertEqual(wizard.bill_ids, first | second)
        from lxml import etree
        view = etree.fromstring(self.env.ref('tha_vhg_staff_credit_report.view_credit_list').arch_db)
        button = view.xpath('//header/button[@string="Generate Monthly Deductions"]')[0]
        self.assertNotEqual(button.get('display'), 'always')

    def test_browser_wizard_preserves_readonly_selection_on_create(self):
        bill = self._bill()
        model = self.env['tha.staff.credit.operation'].with_context(
            default_mode='deductions', active_model='tha.staff.credit', active_ids=bill.ids)
        # Browser sends mode explicitly but can omit a readonly default field.
        wizard = model.create({'mode': 'deductions', 'company_id': self.company.id, 'month': '2026-09-01'})
        self.assertEqual(wizard.bill_ids, bill)
        from lxml import etree
        arch = etree.fromstring(self.env.ref('tha_vhg_staff_credit_report.view_operation').arch_db)
        self.assertEqual(arch.xpath('//field[@name="bill_ids"]')[0].get('force_save'), '1')
        action = wizard.with_user(self.manager).action_generate()
        self.assertEqual(self.env['account.move'].search(action['domain']).line_ids.tha_staff_credit_id, bill)
