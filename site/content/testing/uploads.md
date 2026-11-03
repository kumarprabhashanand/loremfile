An upload form has to decide three things about every file. Is it too big? Is it what it claims
to be? Can the code behind the form process it? Each file below sits on the edge of one of those
decisions. Every one has a stable URL, so your test can fetch it instead of committing it.

## How do I test a size limit?

<!-- file: bin/10mb-minus-1.bin -->

<!-- file: bin/10mb.bin -->

<!-- file: bin/10mb-plus-1.bin -->

These three files are one byte under, exactly on, and one byte over 10 MB in decimal units. A
limit of 10,000,000 bytes accepts the first and refuses the last. The middle file shows whether
your limit is inclusive. That is the byte a check written with `>` instead of `>=` gets wrong.

<!-- file: bin/10mib-plus-1.bin -->

The same boundary in binary units. If `bin/10mb-plus-1.bin` was accepted, the limit is counting
in MiB. This is the file it should refuse.

<!-- file: edge/zero-byte.pdf -->

An empty file served as `application/pdf`. A form that checks the type but not the length hands
it to a PDF library. The library then fails somewhere less helpful than the upload step.

<!-- file: pdf/10mb.pdf -->

A document whose size cannot be squeezed. Every page embeds a noise image, so a client or proxy
that compresses uploads does not bring it under a limit by accident.

## What is the file really?

<!-- file: edge/pdf-with-png-extension.png -->

A PDF under a `.png` name, served as `image/png`. A check that trusts the extension or the
Content-Type header calls it an image. A check that reads the first bytes finds a PDF signature.

<!-- file: edge/pdf-zip-polyglot.pdf -->

A valid PDF and a valid zip archive in the same bytes. Magic-byte sniffing calls it a PDF.
Anything that later unpacks archives finds a file inside. Some scanners refuse polyglots
outright. Decide what your form does with one.

<!-- file: heic/640x480.heic -->

HEIC, the format iPhones capture photos in. A form that previews uploads in the browser has to
convert it or show a placeholder, because not every browser displays HEIC.

## Which images change when decoded?

<!-- file: jpg/exif-orientation-8-640x480.jpg -->

The pixels are stored rotated, with an EXIF tag that says how to turn them upright. A
thumbnailer that strips metadata without applying the tag publishes the card sideways.

<!-- file: jpg/cmyk-640x640.jpg -->

CMYK instead of RGB. Image code that assumes three channels either rejects it or produces the
wrong colours.

<!-- file: jpg/4000x3000.jpg -->

Twelve megapixels in under 300 KB. A resizer that decodes the whole image before scaling holds
every one of those pixels in memory, for a file that small. So limit pixels as well as bytes.

## What can an archive do?

<!-- file: edge/zip-directory-traversal-name.zip -->

A readable zip with an entry named `../evil.txt`. Code that extracts uploads by joining each
entry name to a target directory, without checking it, writes outside that directory.

<!-- file: zip/zip64-70000-empty-files.zip -->

More entries than a classic zip header can count, so it needs ZIP64. A server that limits
uploads by entry count and reads only the classic two-byte count sees the wrong number.

<!-- file: zip/aes256-password-loremfile.zip -->

Encrypted with the password `loremfile`. A virus scanner or content check cannot look inside.
The form needs a rule for archives it cannot inspect.

<!-- file: zip/empty.zip -->

A valid zip with nothing in it, which plenty of readers reject. Accept it or refuse it, but do
it on purpose.

To see why a broken file fails, and what each outcome means, read
[testing parsers and error handling](/testing/parsers).
