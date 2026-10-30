# VHG Staff Credit Report (Odoo 19)

Fresh-install module, version 19.0.2.0.6. Open **Accounting > Reporting > Other Reports > Staff Credit Report** (`/odoo/staff-credit-report`). This is the only module menu. The previous register/report/import/accounts screens and PDF/native accounting report have been removed.

## Setup and bills

Assign Staff Credit Reader or Manager. Managers maintaining bills need access to the source accounting documents. Generating monthly drafts additionally requires Accounting (`account.group_account_user`); posting follows native Accounting permissions. Readers see public employee information, not private HR data.

Select one company, click **Settings**, and choose its reconcilable Staff Credit account (suggested code 130100), salary expense account (suggested 701010), and general deduction journal. No accounts or original bills are created automatically.

Create a bill and select an existing posted invoice or journal entry, then its Staff Credit debit item. A single qualifying debit is selected automatically. Source date, partner and amount default from that item. A combined source debit may be split between bill records without exceeding its amount. Use company currency only. Select the responsible staff member, department at the time of charge, description, category, Anzer reference and optional authorization information. The original invoice/entry remains clickable.

Set Repayment from and installment count, then **Generate Repayment Plan**. Equal installments are rounded in company currency; the last installment absorbs the difference. Edit unused installment amounts/dates to match the agreement or skip months. The plan must equal the original bill and its count must match before generating deductions. Authorization is informational.

## Monthly review

Open a saved staff-credit bill and click **Generate Monthly Deductions**, or select multiple bill rows in the list to reveal the same action. Choose the month; only those bills are included. The selected bills are shown in the wizard and must belong to one company. It creates one month-end **draft** per staff member: Dr salary expense / Cr Staff Credit, with a separate credit line per bill. Review and post using normal Accounting actions. This does not run payroll, create original bills, automatically post, or reconcile receivables.

Repeated generation opens the existing entry without duplicating selected bills. Selecting additional bills for the same staff and month adds their installments to that staff member's existing draft and updates its salary debit. Additional bills cannot be added to a posted/cancelled batch; review it instead. To replace an unused batch, delete its draft and generate it again. Linked installments are protected until draft deletion. Posted deductions require standard reversal; a reversal restores the staff balance from its accounting date onward. The original month's batch is not generated again after reversal. Draft reservations and posted settlements cannot exceed original debt. Foreign-currency source items are rejected.

Use **Existing settlements** for historical repayments or adjustments, allocating existing posted credit items to bills. Generated credits count automatically and cannot be allocated again. Remove manual source links before correcting/reversing those external entries; retain approved exports for audit. Original bill sources are protected while linked.

## Excel report

**Export Excel** accepts company, month, staff, department, category and month-end open/settled filters. These wizard filters determine the output, independently of list selection. The 14 columns follow the latest supplied information template: No, Date, Staff name, Department, Name (Patient & Others), 100% Bill, Settlement up to month, Times, month amount, Balance for month, Remark, System Reference, Anzer System invoice, Odoo System invoice.

Settlement includes posted amounts through month-end, including dated generated reversals. Balance equals bill less that settlement. Month amount is planned even while the entry is draft; Times is the scheduled installment ordinal (1/3 in the first scheduled month), blank in a skipped month. System Reference is the SC record reference; Odoo System invoice is the original document number. The workbook contains one table with blue headings, totals, filters and frozen headings. It does not contain the template's workflow notes.

Historical calculations use accounting dates, not today's residual balance. Editable metadata/plans and manual allocations are not immutable month-close snapshots: retain approved monthly exports.

## Validation

Use Docker and local database THA. See VALIDATION.md for the verified run. All automated fixtures roll back. No migration, live import or demo-seeding script is included. Existing prototype installations must be reviewed and uninstalled before a fresh install; uninstall removes module records but must preserve accounting documents.
