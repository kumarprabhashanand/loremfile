A Jupyter notebook is JSON with a specific shape, and the tools that render one — repository
browsers, documentation sites, review tools — need a file whose outputs already exist so they
have something to display without executing anything.

`ipynb/simple-with-outputs.ipynb` is nbformat 4 with three cells: one Markdown cell and two
code cells, with an execution result and a stdout stream already stored in the file. Nothing
needs to run for a renderer to show something meaningful.

No cell records a run time. Notebooks routinely carry execution timings in their metadata,
which makes them different on every save and noisy in version control; this one deliberately
carries none, and a validator rejects the file if any appear. That also makes it a stable
fixture to commit and compare.

Use it to test notebook renderers, converters to HTML or PDF, and diff tools that have to
treat a notebook as more than a blob of JSON. Related formats: [JSON](/json) and
[Markdown](/md).
