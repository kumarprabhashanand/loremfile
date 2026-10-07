**loremfile.dev**: sample files you can hotlink, or download for tests that run offline.

Free and CC0, with stable URLs. PDFs, images, audio, video, office documents, data files,
text in many encodings and exact-size binary blobs. Open CORS, byte ranges and a SHA-256
manifest. No ads, no signup, no keys.

- **Hotlink** the URL from a page or a test: `https://loremfile.dev/pdf/a4-3pages.pdf`
- **In a GitHub workflow**, the action downloads files and checks each hash:
  `uses: kumarprabhashanand/loremfile/action@action-v1` with `paths:` or `formats:`
- **From the command line**, the client takes named files or a whole format:
  `npx loremfile get --format pdf`, or `loremfile get --format pdf` after `pip install loremfile`
