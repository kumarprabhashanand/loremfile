XLSX is Excel's workbook format, and the one import screens and data pipelines are asked to
read more than any other. These workbooks cover the shared people dataset and the cell-level
details that trip readers.

`xlsx/1sheet-10rows.xlsx` and `xlsx/1sheet-1000rows.xlsx` hold one sheet with a bold, frozen
header row and ten or a thousand records of the people dataset; the first ten rows are the
same in both.

`xlsx/with-formulas.xlsx` has SUM, AVERAGE, IF and VLOOKUP formulas over a ten-line order
table, each with its result cached in the file, so readers that do not calculate, such as
pandas, still see values. `xlsx/with-types-and-formats.xlsx` has one row per cell type and
number format, including dates, percentages, currency and text that only looks numeric, such
as 007.

For size limits, `xlsx/1mb.xlsx` and `xlsx/10mb.xlsx` add a sheet of incompressible noise
images. Related formats: [CSV](/csv), [DOCX](/docx) and [Parquet](/parquet).
