# VHG Staff Credit Report (Odoo 19)

Tracks staff receivables against existing posted accounting entries, with an editable monthly plan, allocations, CSV validation, screen reports, Excel and A3 landscape PDF. No report or register action creates entries, reconciles journal items, or runs payroll.

## Setup

1. Install `tha_vhg_staff_credit_report` with dependencies `account`, `hr`, `mail` and Python `xlsxwriter`.
2. Assign **Staff Credit / Reader** or **Staff Credit / Manager** in user permissions. Admin initially receives Manager. Reader includes accounting read access; Manager adds register/configuration/import access, without granting payroll or private employee access.
3. Select the hospital company. Open **Accounting > Staff Credit > Accounts**, select the company and its reconcilable receivable account. The default looks up `130100` in that company's chart. Configuration is explicit: no company IDs or account IDs are hard-coded in business code.
4. Ensure staff have employee records, departments, work contacts and a unique contact **Reference** for CSV imports. The register uses `hr.employee.public` to avoid private HR permissions. Archived staff remain reportable.

## Daily use

Create one Register record per hospital bill or other staff debt. Select its posted debit journal item, responsible staff, accounting partner, department at charge date, description, amount and repayment terms. Source date and partner must match the journal item. Multiple records can split one aggregated debit, up to its total. A dedicated staff accounting partner is required on each source; partnerless or pooled payroll entries need accounting review in the existing workflow.

Generate equal monthly installments; the final installment absorbs rounding. Edit unpaid amounts or move an unpaid due date to skip a month. One installment is permitted per month. The warning banner identifies inconsistent schedule totals/counts. Paid installments cannot be changed, removed or preceded by inserted installments. Plan generation after any settlement is blocked.

Assign existing posted credit journal items in **Actual settlements**. Select repayment/payroll, credit adjustment, or charge reversal and enter the amount allocated to this charge. One source can settle several charges, with no over-allocation. One charge/source pair is allowed; edit its amount rather than creating a duplicate. Amounts cannot exceed the charge. Classification is explicit: do not label write-offs as payroll repayments.

**Suggest reconciled settlements** proposes unallocated credit lines already reconciled by accounting against an unsplit charge debit. Review classification and confirm before any allocation is created. Ambiguous splits, already allocated sources and unreconciled entries require manual assignment. No matching by employee name or automatic oldest-debt matching is performed.

Linked entries are protected against draft/cancellation and accounting-source edits. A manager must remove the affected allocations/register links before accounting corrects those sources. All link and schedule changes are recorded in chatter. Attach patient evidence to the charge chatter, not to public attachments. Normal Odoo attachment permissions apply to the secured parent record.

## Monthly report

Open **Monthly Report**, select a company/month, optionally staff/department/category/open-or-settled status, and refresh. Excel and PDF always recalculate from accounting links; refresh the on-screen preview after changing filters or allocations.

- **100% Bill** includes charges posted by selected month-end, including new charges during the month.
- **Prior settlements** are all allocated credits dated before the selected month, including classified adjustments/reversals.
- **Balance** = charge less prior settlements; it is before selected-month deductions, and includes current-month additions.
- **Monthly planned** is the agreed schedule amount due in that month. Later payments do not rewrite it.
- **Times** is fully paid installments through the previous month divided by scheduled installment count. Only repayment-classified allocations count as paid installments; partial payments carry to the earliest unpaid installment. Adjustments/reversals reduce debt but do not falsely count as paid installments.
- **Actual** is the selected month's allocated credits; **Closing** subtracts them from Balance.
- Status filters use **month-end** balance, not today's balance. Historical calculations use source accounting dates, not current reconciliation residuals.

The screen and Excel detail show actual/closing amounts. Excel includes signed **Movements** and **GL Reconciliation** sheets; PDF prints the reference layout and the company reconciliation summary. All monetary values use company currency and its rounding. Version 1 rejects source journal items with a different currency; foreign-currency schedules are out of scope.

### Reconciliation

Company-wide totals are deliberately independent of staff/category/status filters:

`Opening + charges during month - reductions during month = register closing`

`GL balance - register closing = unlinked debits - unapplied credits`

Every nonzero unallocated source appears in the screen and Excel audit list, including partially allocated items. Unlinked and unmatched accounting items are never silently assigned. Reconcile to the source ledger with the same company, account, posted-only filter and month-end cutoff. A zero difference alone is insufficient if equal unlinked debits and unapplied credits offset; review both amounts.

Historical figures reflect current validated metadata and allocations applied to historical accounting dates. This is not an immutable month-close archive. Save approved monthly exports and restrict Manager access. Accounting changes require removing links first and then revalidating/relinking the affected records. Automated repayment reversals/refunds and changes to settled schedules are outside v1; correct mistaken links through the manager workflow and audit trail rather than entering negative allocations.

## CSV import

Download the UTF-8 CSV template from **Staff Credit > Import**. Replace example rows. The importer accepts up to 5,000 rows per file, in template column order. Amounts are plain decimals (no thousands separators). Dates are ISO `YYYY-MM-DD`.

- `charge` rows: unique `external_key`, staff work-contact Reference as `staff_identifier`, exact company department, charge date/category/description, posted move reference and journal code, line number, amount, start month and installment count. Category keys: `hospital`, `damage`, `penalty`, `meals`, `other`.
- `schedule` rows: `external_key`, `due_date`, `amount`. An existing scheduled month is updated; a new month is added. Plan total/count must still match. To skip a generated month during bulk setup, edit that charge's schedule in the register before importing settlements.
- `settlement` rows: charge `external_key`, posted move reference, journal code, line number, amount and `kind` (`repayment`, `adjustment`, `reversal`). Existing imported charges can receive subsequent settlement rows.

Line number is **1-based among ALL journal items of the entry ordered by database journal-item ID**, not the visible debit-only subset or a spreadsheet row number. Retrieve source IDs/references from the target database; do not reuse IDs from another database. The importer resolves references inside the selected company and refuses ambiguity.

Put charges first, schedule overrides second, settlements last. **Validate only** executes real constraints inside a rolled-back savepoint; no register/accounting data is saved. **Validate and import** repeats validation and saves all rows atomically. One invalid row rolls back the entire file and returns row errors. Duplicate charge keys/source references are rejected; importing an existing charge again does not update it or create another entry. Validation previews consume PostgreSQL sequence values, so register IDs may have gaps.

Collect the source workbook, employee/partner mapping, agreed schedules and posted GL details before preparing the live import. Reconcile totals before rollout. Installation alone does not reconstruct history or change the hospital issue's completion status.

## Local validation

Run in the project Docker environment, database `THA`:

```powershell
docker exec odoo_19 odoo -d THA -i tha_vhg_staff_credit_report --stop-after-init --http-port=8079 --gevent-port=8089 --max-cron-threads=0 --test-enable --test-tags /tha_vhg_staff_credit_report
docker restart odoo_19
Get-Content .\logs\server.log -Tail 300
```

Use `-u` after later updates and bump the manifest version for code/config changes. Tests run in rollback transactions using clearly named Thukhasaytanar fixtures. The optional local demo script under `scripts/` is explicitly restricted to THA and creates labeled demo accounting data; never run it on live.
