# Staff Credit: user workflow

Open **Accounting → Reporting → Other Reports → Staff Credit Report**.
Select **Shop Sphere** in the company switcher for the local examples.

## 1. Set up the company once

A Staff Credit Manager configures **Settings** from the list:

| Setting | Shop Sphere example |
| --- | --- |
| Staff Credit account | 130100 Receivable - Internal Under HOD (Staff Credit), reconcilable Receivable |
| Salary expense account | 701010 Salary & wages |
| Deduction journal | Staff Credit (STCR), Miscellaneous/general journal |
| Original bill revenue account | 500115 Services Income - Staff Medical Bills |

These accounts follow the supplied workflow template. Confirm the approved account mapping before using it in another company. Settings are separate for each company. **Settings** on a saved bill can override deduction settings; **Save as company default** also changes defaults for future bills.

Staff Credit Readers can review and export. Staff Credit Managers maintain bills. Generating deductions also requires Accounting access; posting requires the normal Accounting permissions. Employees and their work contacts must already exist in the selected company.

## 2. Post the original bill or journal entry

Create the source document in Accounting using the correct company and staff partner. The source must contain a debit to the configured Staff Credit account, in company currency.

For the supplied Anzer workflow, post a balanced journal entry:

| Account | Debit | Credit |
| --- | ---: | ---: |
| 130100 Staff Credit, with the staff partner | Full bill amount | |
| Revenue account | | Full bill amount |

Enter the actual charge date, description, reference and receivable due date. Post it. Do not post the same Anzer bill twice if it already exists in Odoo. An existing posted customer invoice is also supported when its receivable debit uses the configured Staff Credit account.

## 3. Create one Staff Credit bill

1. Click **New** in Staff Credit Report.
2. Confirm the company and choose **Original invoice / entry**.
3. Choose **Staff Credit debit item**. A single qualifying item is selected automatically. Check the source date, partner and **100% Bill** amount.
4. Select the responsible **Employee** and **Department**. Enter **Category** and **Patient / other description**.
5. Enter the original **Anzer System invoice** reference when available. Put legacy references and useful context in **Notes and authorization → Note**. The Odoo source document is kept as a separate link.
6. Set **Repayment from** and **Installment count**. Save.
7. Record the actual authorizer and date if required by your approval process. These fields record information; they do not trigger an approval workflow.

Each company has its own running reference: `SC/<company ID>/000001`, `000002`, etc. Existing references are retained when a sequence is first introduced; new numbers continue after the highest existing suffix. Numbers may have gaps after cancelled/rolled-back operations.

## 4. Generate and review the repayment plan

Click **Generate Repayment Plan** and confirm. The system splits the bill into equal monthly installments, with rounding adjusted in the final installment.

Check all dates and amounts. You can change an unused installment's due date or amount, including moving it to skip a month. Keep one installment per month, the total equal to the bill, and the number of rows equal to **Installment count**.

The plan button disappears after a plan exists. **Deduction created** means an entry has been generated for that installment; it does not mean it has been posted or paid.

## 5. Generate the month's deduction, then post it

1. Open the saved bill, or select one or more bills in the list from the same company.
2. Click **Generate Monthly Deductions**.
3. Choose the repayment month and check the selected bills/employees.
4. Click **Generate / Open Drafts**.
5. Open each returned draft in Accounting. Review the staff, month-end date, journal and amount.
6. Post the entry when approved.

The generated entry is **Dr 701010 Salary & wages / Cr 130100 Staff Credit**, with the staff partner on the credit. One draft is generated per employee per month. Multiple selected bills for that employee have separate credit lines in that draft.

**Only posted entries reduce the Staff Credit balance.** Drafts reserve the scheduled amount but leave the bill unpaid. Generation does not process payslips, transfer cash, automatically post entries, or reconcile receivables.

Repeat for later months as they become due. Generating again reopens the existing deduction instead of duplicating it. Additional selected bills can be added while the employee's monthly entry is draft. A posted monthly batch cannot accept new bills.

## 6. Review partial and completed repayment

The list and bill form show **100% Bill**, **Settled Amount**, and **Balance**. Open **Generated deductions** to review linked accounting entries and their posting states.

- **Partial:** some installments are posted; Balance remains positive.
- **Not yet settled:** there are no posted settlements, even if a draft deduction exists.
- **Completed:** posted settlements equal the bill and Balance is zero.

An accountant can reconcile the original receivable debit with the posted deduction credits in Accounting. Reconciliation is separate from the report's settlement calculation. Do not link generated deductions again under **Existing settlements**.

Use **Existing settlements** only to allocate a historical/manual posted credit that has the same account, partner, company and currency, dated on or after the bill. Enter the amount allocated to this bill. The module prevents allocation beyond the source credit or bill amount.

To correct an unused generated deduction, delete its draft and regenerate it. Correct a posted deduction with the standard reversal workflow; its effect is reversed from the reversal's accounting date. A reversed monthly batch is not generated again. Ask Accounting to review any correction rather than duplicating a settlement.

## 7. Export Excel

| Starting point | Included records |
| --- | --- |
| List, no rows selected | All records in the chosen company that match the export wizard filters |
| List, rows selected | Only the selected bills, further narrowed by optional filters |
| Saved bill form | Only the open bill; its employee, department and category are prefilled |

Click **Export Excel**, check the company and filters, then click **Export Excel** in the dialog. List search filters are not automatically copied into the export wizard: select the desired rows or set the wizard filters explicitly.

Choose any date in the desired **Month** to report through that month's end. Leave it blank to include all charge months and calculate settlements through today. Employee, Department, Category and Status are optional filters; **All** status includes open and completed bills.

In the workbook:

- **100% Bill** is the original linked charge.
- **Posted through [date]** is cumulative posted settlement, including dated reversals.
- **Times** is the scheduled installment number for the reporting month, such as `2/6`; it is not a count of paid installments. It is blank when no installment is planned that month.
- **Planned amount** is the installment scheduled for that month, whether draft, posted or not generated. For an all-months export, this column and Times refer to the current month, as labelled.
- **Balance as at [date]** is the original charge less posted settlements through that date. Positive balances are highlighted amber; zero balances are green.
- **System Reference** is the Staff Credit reference. **Anzer System invoice** is the external reference. **Odoo System invoice** is the original Odoo source document number.

The report includes totals, frozen headings, filters and landscape printing. Save approved monthly exports: changing metadata, schedules or historical settlement links can affect regenerated reports.

## Local example assumptions

Shop Sphere examples available for review:

| Reference | Employee | Bill (MMK) | Posted settlement (MMK) | Balance (MMK) | State |
| --- | --- | ---: | ---: | ---: | --- |
| SC/4/000001 | Aye Aye Aung | 195,500.00 | 195,500.00 | 0.00 | Fully repaid |
| SC/4/000002 | Ye Min Oo | 60,675.00 | 10,112.50 | 50,562.50 | One of six installments posted |
| SC/4/000003 | Win Lai Lai Sein | 26,501.00 | 26,501.00 | 0.00 | Fully repaid |
| SC/4/000004 | Aung Kyaw Htay (ID) | 470,000.00 | 0.00 | 470,000.00 | October deduction draft only |

The first local example was previously SC/4/000174. Its chatter records the renumbering; old posted accounting labels retain that former reference.

Examples are copied or adapted from the issue's supplied workbook solely for local Shop Sphere review. They are labelled in each bill's Note. Original spreadsheet references are retained as source references, not reused as newly issued Odoo document numbers. Repayment months inferred from the workbook are stated in the notes. They are not a live hospital historical import.
