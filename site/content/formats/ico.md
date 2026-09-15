ICO is the Windows icon format, and the format of `favicon.ico`. A real favicon is rarely one
image: an ICO file is a small directory of images at different sizes, and the browser or
operating system picks the one that fits.

`ico/favicon-16-32-48.ico` contains three images, at 16x16, 32x32 and 48x48 pixels, the shape
a real favicon has. Software that reads only the first entry, or assumes an ICO holds a
single image, shows the wrong size or fails outright.

Use it to test favicon handling in crawlers and link previewers, icon extraction in file
managers, image libraries that must choose an entry, and upload forms that accept icons.
Because each entry is a different size, it also checks that a thumbnailer picks the largest
image instead of scaling up the smallest. For single-resolution images, see [PNG](/png).
