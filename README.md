# VHG Staff Credit Report (Odoo 19)

Version 19.0.2.0.28. Open **Accounting > Reporting > Other Reports > Staff Credit Report** (`/odoo/staff-credit-report`). This is the only module menu. See [USER_GUIDE.md](USER_GUIDE.md) for step-by-step setup, posting, repayment and export instructions.

## Setup and bills

Assign Staff Credit Reader or Manager. Managers maintaining bills need access to the source accounting documents. Generating monthly drafts additionally requires Accounting (`account.group_account_user`); posting follows native Accounting permissions. Readers see public employee information, not private HR data.

Select one company, click **Settings**, and choose its reconcilable Staff Credit account (suggested code 130100), deduction debit account, optional original-invoice income account (suggested code 510585), and general deduction journal. The debit account can be an Expense account (suggested 701010) or a Cash/Bank account used as a clearing account. The generated monthly entry debits this configured account and credits Staff Credit.

Create a bill and either select an existing posted invoice or journal entry, or save its details as a draft Staff Credit bill and click **Create Draft Invoice**. The generated customer invoice uses the configured Staff Credit receivable and income accounts, with no taxes. It remains in Draft until Accounting posts it; posting activates the Staff Credit bill and links the receivable line. Cancelling the draft invoice marks the Staff Credit bill Cancelled. Draft and Cancelled bills do not enter Excel reports or repayment processing.

For an existing source, when it contains exactly one qualifying Staff Credit debit, that item is selected automatically and the debit-item selector is hidden. The selector appears for multiple qualifying debits so the user can choose the correct line, or when none qualify so the missing source is visible. Source date, partner and amount default from the selected item. A combined source debit may be split between bill records without exceeding its amount. Use company currency only. Select the responsible staff member, department at the time of charge, description, category, Anzer reference and optional authorization information. The original invoice/entry remains clickable.

Set Repayment from and installment count, then **Generate Repayment Plan**. Equal installments are rounded in company currency; the last installment absorbs the difference. Edit unused installment amounts/dates to match the agreement or skip months. The plan must equal the original bill and its count must match before generating deductions. Authorization is informational.

## Monthly review

Open a saved staff-credit bill and click **Generate Monthly Deductions**, or select multiple bill rows in the list to reveal the same action. Choose the month; only those bills are included. The selected bills are shown in the wizard and must belong to one company. It creates one month-end **draft** per staff member: Dr the configured deduction debit account (Expense or Cash/Bank clearing) / Cr Staff Credit, with a separate credit line per bill. Review and post using normal Accounting actions. This does not run payroll, create original bills, automatically post, or reconcile receivables.

Repeated generation opens the existing entry without duplicating selected bills. Selecting additional bills for the same staff and month adds their installments to that staff member's existing draft and updates its salary debit. Additional bills cannot be added to a posted/cancelled batch; review it instead. To replace an unused batch, delete its draft and generate it again. Linked installments are protected until draft deletion. Posted deductions require standard reversal; a reversal restores the staff balance from its accounting date onward. The original month's batch is not generated again after reversal. Draft reservations and posted settlements cannot exceed original debt. Foreign-currency source items are rejected.

Use **Existing settlements** for historical repayments or adjustments, allocating existing posted credit items to bills. Generated credits count automatically and cannot be allocated again. Remove manual source links before correcting/reversing those external entries; retain approved exports for audit. Original bill sources are protected while linked.

## Native Odoo import

Use Odoo's standard **Import** action on the Staff Credit list for backdated or bulk entries. Map the required company, employee, department, partner, charge date, description, bill amount, repayment start month and installment count fields. Imported bills remain in Draft until their invoice is created and posted. Open each imported bill and click **Create Draft Invoice** to create its customer invoice using the configured Staff Credit debit and Original Invoice credit accounts; post it through Accounting to activate the bill. This is Odoo's normal list import, separate from the repayment **Export Excel** report.

## Excel report

**Export Excel** accepts company, month, staff, department, category and month-end open/settled filters. Selected list rows restrict export to those bills; without a selection it covers matching company records. From a bill form, only that bill is included and employee, department and category are prefilled. The 14 columns follow the supplied two-row header design, with grouped settlement/month labels, alternating row shading, highlighted balances, wrapped notes and a green total row. Blank Month means all charge months with settlements and completed repayments through today; planned amount refers to the current month.

Settlement includes posted amounts through month-end, including dated generated reversals. Balance equals bill less that settlement. Month amount is planned even while the entry is draft. Times shows completed / total repayments, such as 3/5, using cumulative posted settlement to cover installments oldest first. Partial installments do not count as completed; drafts do not count, and reversals reduce progress from their accounting date. Progress stays visible in skipped months and after the plan ends. Before a plan is generated, the configured equal installment amounts are used. System Reference is the SC record reference; Odoo System invoice is the original document number. The workbook contains one table with blue headings, totals, filters and frozen headings. It does not contain the template's workflow notes.

Historical calculations use accounting dates, not today's residual balance. Editable metadata/plans and manual allocations are not immutable month-close snapshots: retain approved monthly exports. Settings from the list edits company defaults; Settings from a bill opens an override wizard. The override applies to that bill's deductions and changes company defaults only when **Save as company default** is checked.

## Validation

Use Docker and local database THA. See VALIDATION.md for the verified run. All automated fixtures roll back. No migration or demo-seeding script is included. Historical entry import is available through the Staff Credit list. Existing prototype installations must be reviewed and uninstalled before a fresh install; uninstall removes module records but must preserve accounting documents.
