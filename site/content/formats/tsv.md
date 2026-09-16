TSV separates fields with tabs instead of commas. That avoids most quoting problems, because
commas and quotes in the data need no escaping, which is why spreadsheet exports, scientific
tools and databases often use it. It still breaks tools that assume commas or turn tabs into
spaces.

`tsv/people-1000.tsv` holds 1,000 rows of the shared synthetic people dataset with a header
row, delimited by tabs. The rows are the same records as the CSV and JSON people files, so you
can import both and check that the results are identical.

Use it to test import dialogs that must detect the delimiter, command-line tools such as `cut`
and `awk`, spreadsheet uploads, and paste handling in web forms. It is UTF-8 with LF line
endings and no byte-order mark. Related formats: [CSV](/csv) and [JSON](/json).
