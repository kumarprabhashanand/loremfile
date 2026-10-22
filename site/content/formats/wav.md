This is a sample WAV file: uncompressed PCM audio in the CD format, free to hotlink or
download.

<!-- file: wav/sine-440hz-3s-44k-16bit-stereo.wav -->

`wav/sine-440hz-3s-44k-16bit-stereo.wav` starts its samples at byte 44, behind the canonical
header that hand-written readers assume. A reader that skips that header by length instead
of walking the chunks breaks on `wav/sine-440hz-3s-48k-24bit-stereo.wav`, whose extensible header
puts the samples at byte 68, on `wav/sine-440hz-3s-44k-32bit-float-stereo.wav`, whose float
header and `fact` chunk put them at 58, and on `wav/with-list-chunk-3s.wav`, whose LIST/INFO
chunk of title and artist tags pushes them to 94.

`wav/sine-440hz-3s-44k-32bit-float-stereo.wav` also breaks code that reads only integers: its
32-bit samples are IEEE float, which such a reader refuses or plays as noise.
`wav/sine-440hz-3s-44k-8bit-stereo.wav` holds 8-bit samples, which WAV stores unsigned with
silence at the midpoint, so a reader that treats them as signed turns that silence into full
scale.

`wav/sine-440hz-3s-44k-16bit-mono.wav` is the canonical file in one channel, for code that
assumes two. `wav/10mb.wav` is exactly 10,000,000 bytes, the 44-byte header plus 16-bit stereo
frames of four bytes each, so its 56,689 ms follow from its size: the file for upload limits
that must be hit to the byte.
