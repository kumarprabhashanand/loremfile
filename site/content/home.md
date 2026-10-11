**loremfile.dev**: sample files you can hotlink, or download for tests that run offline.

Free and CC0, with stable URLs. PDFs, images, audio, video, office documents, data files,
text in many encodings and exact-size binary blobs. Open CORS, byte ranges and a SHA-256
manifest. No ads, no signup, no keys.

- **Hotlink** the URL from a page or a test: `https://loremfile.dev/pdf/a4-3pages.pdf`
- **[Action](https://github.com/kumarprabhashanand/loremfile/tree/main/action)**: in a GitHub
  workflow, `uses: kumarprabhashanand/loremfile/action@action-v1` downloads files and checks
  each hash
- **[pip](https://pypi.org/project/loremfile/)**: `pip install loremfile`, then
  `loremfile get --format pdf`
- **[npm](https://www.npmjs.com/package/loremfile)**: `npx loremfile get --format pdf`
- **[MCP](/docs/mcp)**: `npx -y loremfile mcp` or `uvx loremfile mcp` gives an agent three
  read-only tools

Production is checked from outside every day, and what the check finds is public:
[status](/status).
