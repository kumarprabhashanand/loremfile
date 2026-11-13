You are testing something that takes files, and you need a file to feed it. Say a PDF with
three pages. Every file here has a URL, so you can hotlink it from a page or a test, or
download it and run offline.

Here is one:

<!-- example -->

Paste it into a browser. There is no signup, and no key to send.

<!-- below the grid -->

The files are CC0, so copying one into your own repository is fine. Each has a SHA-256 in our
manifest, and your test can compare it with what it downloaded. A published URL never changes
its bytes, so a hash you save today still matches next month.

Want to fetch files from code? There are four ways:

- **[Action](https://github.com/kumarprabhashanand/loremfile/tree/main/action)** is for GitHub
  workflows. Add `uses: kumarprabhashanand/loremfile/action@action-v1` and it downloads the
  files and checks each hash.
- **[pip](https://pypi.org/project/loremfile/)** gives you a command. Run `pip install loremfile`,
  then `loremfile get --format pdf`.
- **[npm](https://www.npmjs.com/package/loremfile)** does the same without an install step. Run
  `npx loremfile get --format pdf`.
- **[MCP](/docs/mcp)** is for agents. Run `npx -y loremfile mcp` or `uvx loremfile mcp` and the
  agent gets three read-only tools.

We check the live site from outside every day. The results are public on the [status](/status)
page.
